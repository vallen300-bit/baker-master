# BRIEF_BRISEN_LAB_V2_BRIDGE_1 — Cowork↔terminal bridge + Dashboard 2-view (V0.3.5)

**Status:** V0.3.5 RATIFIED 2026-05-03 (Director). Architect-reviewer pass 4 returned 0 Critical + 1 High + 2 Medium + 1 Low ("Add one sentence + one transaction + one acceptance test and the brief is dispatch-ready"); all folded. Ready for Director final OK → B-code dispatch.
**Author:** AI Head 2 (Cowork) → V0.3 amend by AI Head A (terminal AH1)
**Reviewer:** AI Head A (App) + Director
**Build lane:** least-loaded B-code per Lab mailbox state at dispatch time (post-verification)
**Tier:** B (medium); mandatory `/security-review` pre-merge per Lesson #52
**Branch convention:** `aihead-author/brief-brisen-lab-v2-bridge-1` → `b<N>/brisen-lab-v2-bridge-1` (build, N selected at dispatch)
**Target merge ETA:** ~2.5–3 weeks from B-code dispatch (was ~2 weeks pre-Component-6 fold)

---

## 0. Version log + V0.3 ratifications (Director, 2026-05-02 PM)

### V0.3 changes vs V0.2
1. **Q1 RATIFIED — option (c):** per-worker `ratify_authority_level` column. Defaults codified in `bank-model.md` separately:
   - **Director:** ALL tiers (idea greenlight, Tier-B/C ratify, kill criteria)
   - **AI Head A (Cowork + Code terminal AH1):** TIER_B execution ratify (within Director-greenlit lanes)
   - **AH2 (deputy terminal):** TIER_B for review-related ratifies
   - **Architect:** TIER_B for brief reviews
   - **B-codes / Cortex:** NONE
   - Reasoning: option (a) Director-only would have broken Tier-B autonomy lane (decision #13 already ratified). (c) preserves #13 cleanly.
2. **Q2 RATIFIED — option (b):** scoped to `to: [list]` participants + always-Director-included. Cortex self-read filter (decision #4) requires per-recipient filtering; `kind: broadcast` opt-in remains the broadcast path.
3. **OTel RATIFIED — INCLUDE in V2** (acceptance criterion A13). 1-day cost now vs 2-day V3 retrofit. Direct feed for trust-thermostat ritual.
4. **Verify-before-dispatch RATIFIED:** AH2 runs verification on 3 anchor citations (Wiz disclosure URL, AICosts.ai $47K/72h, Anthropic 1,279-session) BEFORE B-code dispatch. ~20–30 min via Grok Heavy + Chrome MCP. Fallback: AH1.
5. **AMENDMENT 1 — DASHBOARD_2VIEW_1 absorbed as Component 6** (in-scope, no longer a carve-out). Spec lives in §4 endpoints + §7 A15–A20. ETA delta: +3–5 days. Stub `BRIEF_BRISEN_LAB_DASHBOARD_2VIEW_1.md` retired (deleted from `briefs/`).
6. **AMENDMENT 2 — Context-renewal hybrid (Hermes-pattern, option c)** (Director ratified 2026-05-02 PM). Token-pressure 4-state machine is the default lifecycle; new optional brief frontmatter `force_fresh_context: true` overrides it for class-change dispatches (e.g., switching B1 from a Cortex matter to a Lab UI brief). Spec in §5.1; AC = A14. ETA delta: +1–2h spec extension on top of existing token-pressure machine (no ETA shift on the brief-total).

### V0.3.1 patch (2026-05-02 PM, post-AH2 verification)

AH2 anchor verification surfaced attribution errors on 3 of 3 H-anchors. Director ratified the corrections in chat:
- **H5 (was "Wiz disclosure, Apr 2026")** → **Lakera research (Elliot W., 2026-04-22)** + Check Point corroboration (Steve Giguere, 2026-04-23). Underlying figures (428/46,500 npm packages, 33 files / 30 packages with live creds) confirmed accurate.
- **H3 (was "AICosts.ai $47K/72h, Q1 2026")** → swap illustrative-$47K-figure for the documented case in the same article: **49 sub-agents running 887K tokens/min for 2.5h via fan-out**. Date framing corrected to "Jul 2025 post; principle re-anchored Q1 2026". Hardening rule (per-worker $/hr ceiling + fleet-wide $/day cap) is unchanged.
- **H4 (was "Anthropic internal retro — 1,279 sessions × 50+ failures")** → drop the 1,279 number (sourced from a leaked source-code comment, ethical/legal weight). Re-anchor on **Anthropic public engineering postmortem (2026-04-23)** which documents the consecutive-failure quality-drop pattern publicly. Hardening rule (per-worker consecutive-failure watchdog) is unchanged.

Follow-up: parallel vault PR to update `wiki/research/2026-05-02-multi-agent-war-stories.md` §1, §3, §4, §5 with the same corrections (separate scope; tracked in §10 anchors).

### V0.3.2 patch (2026-05-03, post-architect-reviewer pass 1)

Architect-reviewer (principal-engineer profile) pass 1 returned: SHIP-WITH-CHANGES, 5 Critical / 6 High / 5 Medium / 3 Low. All Critical + 5 of 6 High folded; H5 promoted to new hardening req **§6 H7** (subagent-impersonation prevention). Director ratified the H7 promotion 2026-05-03.

Concrete changes:
- **C1 / §3 schema** — added `parent_id BIGINT REFERENCES brisen_lab_msg(id)` column + index. Without it, `ratify_decision` middleware cannot resolve `parent_msg.tier_required`; the auth gate would have collapsed on first call.
- **C2 / §4 endpoints + new §4.1** — sender cannot freely declare `tier_required`. Server-side validator looks up the message's `topic` prefix in `_ops/processes/tier-classification.yml` (new file, owned by AI Head A); rejects post if `tier_required` < classification. Topics with no classification default to `director_only` (fail-safe-up).
- **C3 / §3 + §5 wake-mechanism** — renamed `delivered_at` → `wake_attempted_at`; the meaningful "delivered" timestamp is `acknowledged_at` (set when receiver drains inbox). `tmux send-keys` exit-code-0 is no longer treated as delivery confirmation.
- **C4 / §5.1 Hermes-pattern** — `force_fresh_context: true` now uses two-phase shutdown: SIGTERM only when worker is idle (no activity for 5s OR awaiting input prompt); SIGKILL after 60s drain timeout. Mid-tool-call SIGTERM eliminated.
- **C5 / §6 H3 honesty rewrite** — H3 retitled "Wrapper-enforced token-rate ceiling + egress-firewall guard". Added sub-requirement: egress firewall blocks `api.anthropic.com` from any process not running under the wrapper's UID/network namespace. Subagents inherit the wrapper UID OR cannot reach Anthropic at all. Closes the "subagent bypass" attack the H3 lesson actually warns about.
- **H1 / §7 A19** — single-flight `asyncio.Lock` per cache key on `/api/v2/matters` and `/api/v2/terminals` (eliminates cache stampede under load).
- **H2 / §7 A19** — vault YAML files (`slugs.yml`, `cortex-roadmap-current.yml`) loaded into module-level dict at process start; refreshed by background task on 60s timer; endpoints read from in-memory dict (eliminates filesystem hot-path).
- **H3 / §3 indexes** — `idx_msg_topic` now uses `text_pattern_ops` opclass (required for `LIKE 'prefix%'` btree usage under non-`C` locale).
- **H4 / §3 indexes** — replaced `idx_msg_undelivered` with `idx_msg_undelivered_to` (GIN partial on `to_terminals` WHERE wake_attempted_at IS NULL AND deleted_at IS NULL).
- **H6 / §5.1** — every `force_fresh_context` SIGTERM emits `kind: broadcast, topic: lifecycle/restart` to bus before kill (audit trail).
- **NEW H7 / §6** — `ratify_decision` posts require a `human_confirmation_token` issued by a UserPromptSubmit hook within 60s (single-use JWT signed with daemon key). Server-side: missing/expired/replayed token → 403. Closes the subagent-impersonation hole architect surfaced.
- **Medium fixes / §3 + §5 + AC6** — M1 (`WHERE wake_attempted_at IS NULL` on daemon UPDATE); M3 (incident-file dump on flag-flip OFF); M5 (dropped bare `'ratify'` from `kind` CHECK; only `'ratify_required'` and `'ratify_decision'` remain).
- **Deferred to follow-up:** M2 (`body_preview` storage at >1M rows), L1/L2 (ETA + AC line counts).

### V0.3.3 patch (2026-05-03 evening, post-architect-reviewer pass 2)

Pass 2 verified pass-1 fixes mostly landed cleanly, surfaced 3 NEW Critical + 2 NEW High + 3 NEW Medium introduced by the V0.3.2 patches themselves. All folded:

- **NC1 / §4.1** — V0.3.2 seed YAML had `default_tier: director_only` which would have blocked legit Cortex/PR ratify_required traffic on cold start (only Director could ratify, killing Tier-B autonomy lane until AH1 manually extends YAML). Fix: flipped default to `B`, expanded seed taxonomy with all topic prefixes the brief itself uses (`cortex/*/cycle-id/*`, `cortex/*/dispatch/`, `cortex/*/cycle-phase/`, `pr-*/cascade/*`, `lifecycle/*`), added explicit-escalation tags for the 3 high-tier prefixes (`capital-call`, `kill-criteria`, `gold-lock`).
- **NC2 / §6 H7 enforcement primitive** — V0.3.2 said H7 token endpoint was "callable ONLY from UserPromptSubmit hook context" without any mechanism to enforce that. Theatrical exactly like the C2 hole it was promoted to fix. Fix: concrete crypto primitive — SessionStart hook generates an ed25519 keypair, registers the public key with daemon (one-time per session via `POST /auth/register-session-pubkey`); UserPromptSubmit hook signs `{worker_slug, session_id, prompt_hash, ts, nonce}` with the private key; daemon verifies signature against the registered pubkey before issuing the human-confirmation JWT. Private key never leaves hook process memory; injected text in tool output cannot forge signatures (no key access).
- **NC3 / §5.1 idle signal** — V0.3.2 said "no tool-call activity for 5s OR awaiting input prompt" but Claude Code CLI doesn't expose "awaiting input" state. Fallback to 5s would SIGTERM workers mid-LLM-streaming (extended thinking gaps are routinely 5–30s). Fix: dropped the OR-clause; raised threshold to 30s of no wrapper-observed activity. Also added optional secondary path — wrapper exposes `/state` endpoint over Unix socket `/tmp/baker-wrapper-<worker_slug>.sock` reporting `{streaming, tool_call_in_flight, last_activity_ts}`; daemon prefers IPC signal if available, falls back to 30s timeout if not.
- **NH1 / §7 A19** — V0.3.2 spec'd 60s background YAML refresh task without failure semantics. Fix: keep-last-good values on parse failure; emit `kind: broadcast, topic: lifecycle/yaml-refresh-failed` audit event with failure-counter visible in dashboard.
- **NH2 / §6 H7 + §7 A21** — V0.3.2 didn't specify how token's `worker_slug` binds to the caller. Fix: token's `worker_slug` is set server-side from the terminal-key authenticating the `/auth/human-confirmation` call (which is itself bound to the SessionStart-registered pubkey). `ratify_decision` rejects if token's `worker_slug` ≠ caller's terminal-key. A21 test (b) tightened.
- **NM1 / §3 indexes** — `idx_msg_to_terminals` (broad GIN) overlaps with `idx_msg_undelivered_to` (partial GIN). Fix: keep both with explicit comment — broad serves historical "all messages to terminal X" queries; partial serves the hot drain path.
- **NM2 / §7 A21** — test (e) was unimplementable until NC2 enforcement primitive landed. Fix: rewrote to test the actual NC2 mechanism (post with valid terminal-key but no signed payload from registered session pubkey → HTTP 403).
- **NM3 / §3 + §5** — `acknowledged_at` was written from two paths (worker UPDATE + endpoint), implying workers had direct DB write access. Per H1 vault scoping, workers should not have raw DB credentials. Fix: dropped "worker UPDATE" path; all `acknowledged_at` writes go through `POST /msg/<id>/ack` endpoint owned by daemon.
- **L3 / §8 lane step 10** — pass 1 flagged `--force-with-lease` as inconsistent with Baker convention. Fix: rebase + standard merge; no force-push (force-push to main is globally forbidden per `~/.claude/CLAUDE.md` hard rules).

### V0.3.4 patch (2026-05-03 evening, post-architect-reviewer pass 3)

Pass 3 returned 0 Critical, 3 High, 3 Medium, 2 Low — architect verdict: "ship-ready after those fixes." All folded:

- **H-A1 / §7 A14 test (b)** — V0.3.3 §5.1 dropped the "5s OR awaiting input" wording but A14 test (b) still carried it (text rot). Fix: rewritten to mirror §5.1 exactly (preferred wrapper IPC `/state` reports `streaming==false AND tool_call_in_flight==false AND last_activity_ts ≥ 30s`; fallback 30s no-wrapper-observed-activity).
- **H-A2 / §3 indexes** — A18 matter-card "open Director-Qs count" query had no supporting index. The two existing indexes both miss the predicate combination. Fix: added partial btree `idx_msg_open_ratifies (topic text_pattern_ops) WHERE kind='ratify_required' AND acknowledged_at IS NULL AND deleted_at IS NULL`. Serves the matter-card query directly; degrades gracefully under retention-forever.
- **H-A3 / §3 schema + §5.1 H6 audit handler** — session-key TTL on worker crash had a 24h hole. Fix: chose architect's option 3 (couple key-expiry to wrapper liveness via H6 audit handler). When `lifecycle/restart` event fires (Phase 1 SIGTERM or Phase 2 SIGKILL), the same daemon code path UPDATEs `brisen_lab_session_keys SET expired_at = NOW() WHERE worker_slug = <restarting_worker> AND expired_at IS NULL`. Also retained the 24h fallback sweep for crashes that bypass the lifecycle path.
- **M-A1 / §4.1 default_tier provenance** — clarified that `default_tier` is loaded from YAML AT process start into a module-level constant; on YAML refresh failure, the in-memory constant retains its last-good value (NH1 keep-last-good extends to this specific field). YAML field is the SOURCE; in-memory constant is the RUNTIME truth.
- **M-A2 / §3 schema** — `brisen_lab_session_keys.session_id` now uses `DEFAULT gen_random_uuid()`; `POST /auth/register-session-pubkey` rejects HTTP 400 if request body includes a client-provided `session_id` (server-issued only).
- **M-A3 / §7 A19** — counter-reset semantics: `yaml_refresh_failure_count` resets to 0 on the first successful refresh after any failure. The 3-strike escalation triggers only on 3 consecutive failures with no intervening success.
- **L-A1 / §7 A2** — migration order specified explicitly: `brisen_lab_msg` → `brisen_lab_worker_authority` → `brisen_lab_session_keys` (FK ordering).
- **L-A2 / §6 H7** — nonce/jti LRU lives in daemon process memory (no Redis dependency). Daemon restart clears the LRU; replay-protection window opens for ≤60s post-restart. Documented as known-and-accepted property; acceptable for Tier-B authorization gate (cost of full distributed nonce store > cost of 60s replay window after deploy).

### V0.3.5 patch (2026-05-03 evening, post-architect-reviewer pass 4)

Pass 4 returned 0 Critical, 1 High, 2 Medium, 1 Low. Architect verdict: "Add one sentence + one transaction + one acceptance test and the brief is dispatch-ready." All 4 folded:

- **H-A4 / §5.1 H-A3 atomicity** — V0.3.4's "same daemon code path emits and UPDATEs" didn't specify ordering or atomicity. Three concrete failure modes (emit-first-UPDATE-fails / UPDATE-first-emit-fails / daemon-dies-between) could re-open the very 24h hole H-A3 was meant to close. Fix: explicit single-transaction wrapping. Daemon executes both as one PG transaction: (1) `UPDATE brisen_lab_session_keys SET expired_at = NOW() WHERE worker_slug = <restarting_worker> AND expired_at IS NULL`, (2) `INSERT INTO brisen_lab_msg (kind, topic, body, ...) VALUES ('broadcast', 'lifecycle/restart', ...)`, COMMIT. Both commit atomically or neither does. On commit failure, daemon logs + the 24h sweep is the documented backstop (no separate recovery path needed). New A14 test (g) verifies expired_at is set in same DB commit as lifecycle/restart row.
- **M-A4 / §7 A21 test (h)** — V0.3.4 added M-A2 client-provided-session_id rejection (HTTP 400) but A21 had no direct test for it (test (g) covered re-registration, a different code path). Fix: added A21 test (h) covering the body-shape rejection branch.
- **M-A5 / §4.1 M-A1 wording** — pass-4 flagged language tension: M-A1 said "Daemon refuses to start (loud failure beats silent wrong default)"; NH1 (line 576) says "Daemon never aborts on YAML failure (silent stale > full Lab outage)." Different scenarios but wording was general enough an implementer could conflate them. Fix: tightened M-A1 to "**at process start, with no in-memory last-good**, daemon refuses to start" — disambiguates from the running-daemon refresh path covered by NH1.
- **L-A3 / §6 H7 LRU cap justification** — appended "(cap chosen for misbehaving-client safety, not steady-state sizing — peak fleet load is ~480 entries; 10K covers pathological burst from a buggy client hitting `/auth/human-confirmation` in a tight loop)".

### V0.2 → V0.1 history (preserved)
V0.1 carried 19 decisions + 6 admin-confirms covering bus + dashboard + new-terminal + autonomy-tier + session-start-digest in a single brief. Director ratified the redraft path 2026-05-02 after both research deliveries (Research 1 + 2) landed.

V0.2 made two changes:
1. **Scope shrink — V0.2 = Cowork↔terminal bridge.** Dashboard 2-view, new Architect terminal, Tier-B autonomy update, and session-start digest were carved out as separate queued briefs. V0.2 kept 10–11 decisions for the bus + 6 admin-confirms hardened.
2. **6 mandatory hardening requirements.** Research 2 (8 production incidents) forced a non-negotiable `§Production Hardening` block. ALL six requirements remain gates for `/security-review` to pass.

V0.3 reverses one carve-out (dashboard 2-view → Component 6) per Director ratification 2026-05-02 PM; the other three (Architect terminal, Tier-B autonomy, session-start digest) remain queued.

---

## 1. Goal (unchanged from V0.1)

Director out of the cross-terminal relay path. Brisen Lab evolves from observe-only (V1, shipped 2026-05-01) to a **message bus + Cowork peer**. Direct cross-terminal coordination compresses the loop ~5–15× while preserving Director audit via Brisen Lab UI.

Today's pain: every cross-agent action (App AI Head A → Terminal AH1, Terminal AH1 → b3, Cortex → Director, etc.) surfaces as a paste-block to Director's clipboard. On batch-ratification days like 2026-05-01 / 02 this is the binding constraint on coordination speed. Audit-only Director model substitutes pre-flight veto with post-hoc visibility — exactly the HOTL pattern Research 1 §Tier-4 Prompt 3 confirms is the converging industry default for one-human-many-agents.

---

## 2. Scope — what V0.2 ships

### KEEP from V0.1 (10-11 decisions + AC1-AC6)

**#1 — No storage cap; 8K-char preview cap on `/api/state` event payloads.**
- Lab event store (Postgres) keeps the full message body indefinitely (subject to retention policy in #12).
- `/api/state` endpoint returns a **preview** truncated at 8,000 chars per event payload (lifted from V1's 500-char truncation that cost App AI Head A visibility on Terminal AH1's "Step 29 — DONE" message).
- Full body retrieved via `/event/<id>/full` endpoint (single-event fetch; no preview cap).

**#2 — Terminals AND Cowork can write to the bus.**
- Both surfaces can `POST /msg/<terminal>` (auth via terminal-key header for terminals; via Baker MCP credential for Cowork).
- Bidirectional: bus is not "Cowork→terminals" or "terminals→Cowork" — it's "any peer → any peer" within the addressing model (#6).

**#3 — Mixed wake-up — minimal scope (dispatch wakes; everything else sits).**
- **Dispatch-class messages** (`kind: dispatch`) trigger active wake-up via class-aware mechanism (tmux send-keys for tmux-backed terminals; SessionStart hook for non-tmux Claude Code; Baker MCP poll-on-session-open for Cowork).
- **All other classes** (`ack`, `broadcast`, `ratify`, `ratify_required`, `ratify_decision`) sit in the inbox and are drained on the worker's NEXT natural turn boundary. No active wake.
- This minimizes wake-noise. Workers running long autonomous cycles (e.g. Cortex Stage 2 V1 cycles) don't get interrupted by routine ACKs.

**#4 — Cortex is a peer; self-read filter prevents cycle pollution.**
- Cortex is a first-class bus peer (terminal namespace includes `cortex` slot). Cortex MUST post cycle events to the bus (`kind: broadcast`, payload: cycle phase + cost + matter slug) for the bridge to be useful — App AI Head A and Director gain visibility into Cortex state without paste-block.
- **Self-read filter:** Cortex's own bus reads MUST exclude its own `kind: broadcast` outputs. Otherwise Cortex Phase 2 reads would surface its own Phase 1 broadcasts as new context, polluting the cycle.
- Implementation: `GET /msg/cortex` accepts `?exclude_self=true` (default true for Cortex worker; false for other readers).

**#5 — Director receives ESCALATIONS ONLY (policy filter).**
- Default policy: Director's bus surface (Brisen Lab UI) shows ALL bus events as read-only audit log.
- BUT: Director receives **proactive notifications** (push, Slack, etc.) only for `kind: ratify_required` OR escalations explicitly addressed `to: [director]`.
- Routine `dispatch` / `ack` / `broadcast` traffic between AI Heads + B-codes does NOT push to Director — it's logged, not pushed. Director can scroll Brisen Lab UI on demand.

**#6 — Addressing terminal AND topic.**
- Every message has BOTH `to: [terminal-list]` AND optional `topic: <slug>` (e.g. `topic: pr-63-cascade`, `topic: cortex-cycle-f7795012`).
- Cortex events use `topic: cortex/<matter>/<cycle-id>` as canonical scheme.
- Enables filtered subscriptions: "show me all messages on `topic: cortex/aukera/*`" without polluting unrelated reads.

**#11 — Threading — minimal viable.**
- Every message carries `thread_id` (UUID; assigned at first message of a conversation; replies share parent's thread_id).
- Threads are linear (no branching). Replies append to thread tail.
- Brisen Lab UI groups by thread_id in the event timeline.

**#12 — Retention forever + soft-delete.**
- Bus events persist forever in Postgres. No automatic hard-delete.
- Soft-delete supported: `DELETE /msg/<id>` sets `deleted_at` timestamp; row stays in DB; `/api/state` excludes by default (`?include_deleted=true` to surface).
- Soft-delete authority: posting terminal can soft-delete its own messages within 5 min of post; Director can soft-delete any message at any time (audit logged).

**#15 — Cowork as a card on Brisen Lab UI.**
- Brisen Lab dashboard adds a `cowork` card alongside the existing 6 terminal cards (lead, deputy, b1-b4).
- Card shows: latest event, current MCP poll status, last `baker_inbox_read` timestamp, last `baker_inbox_post` timestamp.
- Visual parity with terminal cards confirms Cowork's first-class peer status.

**#16 — MCP post + push receive (Cowork integration).**
- New Baker MCP tool pair: `baker_inbox_post` + `baker_inbox_read`.
- `baker_inbox_post`: takes `to: [list]`, `topic`, `kind`, `body`; returns `{message_id, thread_id, posted_at}`.
- `baker_inbox_read`: takes `since_ts` + optional `topic` filter + optional `kind` filter; returns paginated event list.
- **Push receive:** Cowork session-open SHOULD trigger an automatic `baker_inbox_read` on the cowork channel (no manual poll). Implementation: Baker MCP server's session-init hook calls `baker_inbox_read(since_ts=last_seen)` on first tool-use of every Cowork session.

### Admin confirms — AC1-AC6 (hardened per H1-H6 below)

- **AC1** Terminal-key auth headers: per-worker, rotatable, stored 1Password (one secret per worker, scoped vault per H1).
- **AC2** Feature flag `BRISEN_LAB_V2_ENABLED`: env var; default ON after `/security-review` passes; flip OFF triggers SIGTERM kill-switch (per H2) — workers physically halt, fall back to paste-block-via-Director.
- **AC3** Database: Neon Postgres (reuse Baker's existing connection; one backup story; concurrent-write safe). Schema in §3.
- **AC4** Endpoint hosting: extend existing Brisen Lab daemon on Render. New routes: `POST /msg/<terminal>`, `GET /msg/<terminal>`, `GET /event/<id>/full`, `DELETE /msg/<id>`. Auth middleware: terminal-key header validated against 1Password-stored hash.
- **AC5** Mandatory `/security-review` pre-merge per Lesson #52 (new auth surface + new MCP tools + new persisted state). Reviewer: AI Head A (App) + reviewer-rotation if available.
- **AC6** Standing-rule preservation: paste-block-via-Director STAYS as fallback (carve-out, not deprecation). Director audit-only model via Brisen Lab UI (informed without relaying). When `BRISEN_LAB_V2_ENABLED=false` or any worker is unreachable, system falls back to paste-block-via-Director without code rollback.

### NEW IN-SCOPE — Component 6 (V0.3 fold-in)

**Component 6 — Dashboard 2-view + Matter cards.** Folded in from `BRIEF_BRISEN_LAB_DASHBOARD_2VIEW_1.md` (stub retired) per Director ratification 2026-05-02 PM. Detailed spec in §4 endpoints (`GET /api/v2/matters`, `GET /api/v2/terminals`) + §7 A15–A20. ETA delta: +3–5 days.

### CARVE OUT — 3 separate downstream briefs (one-paragraph stubs co-located in this dir)

- `BRIEF_ARCHITECT_TERMINAL_1.md` — V0.1 decisions #14, #17, #18 (new Code terminal "architect" + authority assignment + 3-file memory triplet).
- `BRIEF_TIER_B_AUTONOMY_1.md` — V0.1 decision #13 (Tier B autonomy update; mostly `bank-model.md` standing-rule update, not new code).
- `BRIEF_SESSION_START_DIGEST_1.md` — V0.1 decision #19 (session-start digest behavior; mostly Cowork SessionStart hook update).

Each carve-out becomes its own queued backlog item in `cortex-roadmap-current.yml` (AI Head A handles the roadmap amendment in a separate paste-block). DASHBOARD_2VIEW_1 stub deleted from `briefs/` 2026-05-02 PM (content absorbed as Component 6).

---

## 3. Database schema (Neon Postgres)

```sql
CREATE TABLE brisen_lab_msg (
  id BIGSERIAL PRIMARY KEY,
  thread_id UUID NOT NULL,
  parent_id BIGINT REFERENCES brisen_lab_msg(id),  -- C1: links ratify_decision to its ratify_required parent (auth middleware reads parent.tier_required)
  from_terminal TEXT NOT NULL,
  to_terminals TEXT[] NOT NULL,           -- array of terminal slugs
  topic TEXT,                              -- optional, e.g. "cortex/aukera/cycle-f7795012"
  kind TEXT NOT NULL CHECK (kind IN (
    'dispatch', 'ack', 'broadcast',
    'ratify_required', 'ratify_decision'   -- M5: dropped bare 'ratify' (ambiguous; only ratify_required + ratify_decision are first-class)
  )),
  body TEXT NOT NULL,
  body_preview TEXT GENERATED ALWAYS AS (LEFT(body, 8000)) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  wake_attempted_at TIMESTAMPTZ,           -- C3: set when wake-mechanism call returned exit 0 (e.g. tmux send-keys ok). NOT a delivery confirmation. Renamed from delivered_at to make this clear.
  acknowledged_at TIMESTAMPTZ,             -- AUTHORITATIVE delivery confirmation; set when recipient drains the inbox via /msg/<id>/ack or session UPDATE
  deleted_at TIMESTAMPTZ,                  -- soft-delete
  tier_required TEXT CHECK (tier_required IN ('B','A','director_only')) DEFAULT 'B'
                                            -- only meaningful when kind='ratify_required'; gates which workers may post the matching ratify_decision (Q1 ratification).
                                            -- C2: server-side validator (§4.1) cross-checks against topic→tier classification before INSERT; sender cannot freely downgrade tier.
);

CREATE INDEX idx_msg_to_terminals ON brisen_lab_msg USING GIN (to_terminals);
  -- NM1 (V0.3.3): KEEP this broad GIN despite overlap with idx_msg_undelivered_to. Broad serves
  -- historical "all messages to terminal X" queries (audit trail, dashboard timelines, replay).
  -- Partial below serves the hot drain path. Both needed; documented for future reviewers.
CREATE INDEX idx_msg_topic ON brisen_lab_msg (topic text_pattern_ops) WHERE topic IS NOT NULL;  -- H3: text_pattern_ops required for LIKE 'prefix%' btree usage under non-C locale (matter-card query in A18)
CREATE INDEX idx_msg_thread ON brisen_lab_msg (thread_id, created_at);
CREATE INDEX idx_msg_parent ON brisen_lab_msg (parent_id) WHERE parent_id IS NOT NULL;  -- C1: middleware lookup for ratify_decision auth check
CREATE INDEX idx_msg_undelivered_to ON brisen_lab_msg USING GIN (to_terminals)
  WHERE wake_attempted_at IS NULL AND deleted_at IS NULL;  -- H4: combined GIN+partial covers worker inbox-drain query (replaces V0.3 idx_msg_undelivered which was btree-on-id and didn't help GIN-array workload). NM1 (V0.3.3): documented as complementary to idx_msg_to_terminals above, not redundant.

-- H7 / NC2 (V0.3.3): per-session pubkeys for human-confirmation enforcement. SessionStart hook
-- generates keypair, registers pubkey here. Soft-expire on session-end OR 24h since registered.
CREATE TABLE brisen_lab_session_keys (
  session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- M-A2 V0.3.4: server-issued; endpoint rejects client-provided session_id
  worker_slug TEXT NOT NULL REFERENCES brisen_lab_worker_authority(worker_slug),
  pubkey BYTEA NOT NULL,                         -- ed25519 public key (32 bytes)
  registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expired_at TIMESTAMPTZ,                        -- H-A3 V0.3.4: set by lifecycle/restart audit-handler when worker dies (Phase 1 SIGTERM or Phase 2 SIGKILL); 24h sweep retained as fallback for crashes that bypass the audit path
  CHECK (octet_length(pubkey) = 32)              -- ed25519 pubkey size
);
CREATE INDEX idx_session_keys_worker_active ON brisen_lab_session_keys (worker_slug)
  WHERE expired_at IS NULL;

-- H-A2 V0.3.4: serves A18 matter-card "open Director-Qs count" query
-- (WHERE topic LIKE 'cortex/<slug>/%' AND kind='ratify_required' AND acknowledged_at IS NULL).
-- Without this index the query degrades to seq-scan as table grows under retention-forever.
CREATE INDEX idx_msg_open_ratifies ON brisen_lab_msg (topic text_pattern_ops)
  WHERE kind='ratify_required' AND acknowledged_at IS NULL AND deleted_at IS NULL;

-- Q1 ratification (V0.3, 2026-05-02 PM): per-worker ratify_authority_level column.
-- Defaults codified in baker-vault `_ops/processes/bank-model.md` (separate amendment).
CREATE TABLE brisen_lab_worker_authority (
  worker_slug TEXT PRIMARY KEY,            -- 'director', 'cowork-ah1', 'lead', 'deputy', 'b1'..'b5', 'architect', 'cortex'
  ratify_authority_level INT NOT NULL DEFAULT 0,
  -- 0 = NONE (B-codes, Cortex)
  -- 1 = TIER_B (AH2 review-related, Architect brief reviews)
  -- 2 = TIER_B_EXEC (AI Head A — Cowork + Code terminal AH1 — execution ratify)
  -- 3 = ALL_TIERS (Director only)
  scope_notes TEXT,                        -- e.g. "review-related only", "within Director-greenlit lanes"
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed defaults at migration time (mirrors bank-model.md table — see V0.3 §0):
INSERT INTO brisen_lab_worker_authority (worker_slug, ratify_authority_level, scope_notes) VALUES
  ('director',     3, 'ALL tiers — idea greenlight, Tier-B/C ratify, kill criteria'),
  ('cowork-ah1',   2, 'TIER_B execution ratify within Director-greenlit lanes (AI Head A — Cowork)'),
  ('lead',         2, 'TIER_B execution ratify within Director-greenlit lanes (AI Head A — Code terminal AH1)'),
  ('deputy',       1, 'TIER_B for review-related ratifies (AH2)'),
  ('architect',    1, 'TIER_B for brief reviews'),
  ('b1',           0, 'NONE — implementation only'),
  ('b2',           0, 'NONE — implementation only'),
  ('b3',           0, 'NONE — implementation only'),
  ('b4',           0, 'NONE — implementation only'),
  ('b5',           0, 'NONE — implementation only'),
  ('cortex',       0, 'NONE — Cortex posts ratify_required upward; never decides');
```

**Schema design notes:**
- **C3 rename — `wake_attempted_at` (was `delivered_at`)**: `wake_attempted_at` = wake-mechanism syscall (e.g. `tmux send-keys`) returned exit 0. Does NOT confirm delivery (tmux returns success against paused panes). `acknowledged_at` is the AUTHORITATIVE delivery timestamp — set ONLY when receiver POSTs to `/msg/<id>/ack` (NM3 V0.3.3: workers do NOT have direct DB write access; the ack endpoint owned by daemon is the sole path. This matches H1 vault scoping — workers carry terminal-keys for the API only, no raw DB credentials). Worker drain query: `GET /msg/<terminal>` returns rows where `acknowledged_at IS NULL`; worker iterates and POSTs `/msg/<id>/ack` for each consumed message. Daemon restarts re-attempt wake for any `wake_attempted_at IS NULL`.
- **M1 — UPDATE race:** daemon UPDATE setting `wake_attempted_at` MUST include `WHERE wake_attempted_at IS NULL` predicate to prevent double-write race during deploy roll (Render rolls two daemon instances).
- `body_preview` is a generated column (PostgreSQL 12+) — no application-layer truncation logic; index-friendly; consistent. **M2 deferred:** if retention pushes past 1M rows, drop the generated column and compute preview at SELECT time (no schema migration; just unset GENERATED ALWAYS).
- `to_terminals` as TEXT[] with GIN index supports efficient filtering by recipient.
- **`ratify_authority_level` enforcement (Q1 ratification + C1 + C2 + H7):** `POST /msg/<id>/ratify_decision` middleware:
  1. Looks up parent message via `parent_id` field on the request (HTTP 400 if `parent_id` NULL or `parent.kind != 'ratify_required'`).
  2. Validates `topic`-based tier classification (§4.1 below): rejects HTTP 400 if `parent.tier_required` is below the topic-classified tier (defends C2 downgrade attack).
  3. Reads sender's `ratify_authority_level` from `brisen_lab_worker_authority` keyed on terminal-key. Rejects HTTP 403 if `level < tier_map[parent.tier_required]` where `tier_map = {B:1, A:2, director_only:3}`.
  4. Validates `X-Human-Confirmation-Token` header (H7 — see §6 H7). Missing/expired/replayed → HTTP 403.
  5. On all checks pass: insert new row with `kind='ratify_decision'`, `parent_id` = parent.id, `thread_id` = parent.thread_id; daemon UPDATEs parent.acknowledged_at = NOW() (NM3: server-side write owned by daemon; no worker DB privilege).
  All failure modes return loud 4xx with reason; never silent.

---

## 4. Endpoints (REST API on existing Brisen Lab daemon)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/msg/<terminal>` | terminal-key header | Post a new message. **C2/NC1:** when `kind='ratify_required'`, runs §4.1 topic→tier validator at INSERT time; rejects HTTP 400 if `tier_required` < classification (sender cannot freely downgrade). |
| GET | `/msg/<terminal>?since=<ts>&kind=<filter>&topic=<filter>&exclude_self=<bool>` | terminal-key | Read inbox (paginated; preview cap 8K) |
| GET | `/event/<id>/full` | terminal-key (recipient or sender) | Fetch single event, no preview cap |
| DELETE | `/msg/<id>` | terminal-key (sender within 5min) OR director-key | Soft-delete |
| POST | `/msg/<id>/ack` | terminal-key (recipient) | **NM3:** sole authoritative path to set `acknowledged_at`. Workers do NOT have direct DB write access; all ack writes go through this endpoint owned by daemon. |
| POST | `/msg/<id>/ratify_decision` | terminal-key with `ratify_authority_level` ≥ tier_map[parent.tier_required] **AND** valid `X-Human-Confirmation-Token` header (H7) | For threads waiting on `ratify_required` (Research 1 Steal #1). C1+C2+H7 enforcement chain documented in §3 schema notes. |
| GET | `/api/v2/matters` | terminal-key OR director-key | **Component 6.** Returns matter cards array (5 fields/matter). Reads `cortex_cycles` + `cortex_phase_outputs` + in-memory dict of `cortex-roadmap-current.yml` + `slugs.yml` (H2: dict refreshed by 60s background task; NOT read from vault disk per request). Cache: 60s in-process w/ single-flight `asyncio.Lock` per cache key (H1). |
| GET | `/api/v2/terminals` | terminal-key OR director-key | **Component 6.** Returns 7 cards (lead/deputy/b1-b4 + cowork) + Cortex card. Reads `brisen_lab_msg` + Cortex runtime state. Cache: 15s in-process w/ single-flight lock (H1). |
| POST | `/auth/register-session-pubkey` | terminal-key (called once at SessionStart hook fire) | **NEW (H7 / NC2).** Worker's SessionStart hook generates an ed25519 keypair on session-open, posts ONLY `{pubkey}` (M-A2 V0.3.4: rejects HTTP 400 if request body includes a client-provided `session_id` — server-issued only via PG `gen_random_uuid()` default). Daemon stores `{session_id, worker_slug, pubkey, registered_at}` (one-time registration per session — re-registration with same `session_id` HTTP 409). Returns `{session_id}`. |
| POST | `/auth/human-confirmation` | terminal-key + signed payload (NC2 enforcement) | **NEW (H7 / NC2 V0.3.3).** Body: `{session_id, signed_payload, signature}` where `signed_payload = {worker_slug, session_id, prompt_hash, ts, nonce}` and `signature = ed25519_sign(session_privkey, signed_payload)`. Daemon verifies signature against the registered pubkey for `session_id`; rejects HTTP 403 if signature invalid, expired (`ts > 60s ago`), or replayed (`nonce` already consumed within 60s LRU). On valid: returns `{token: <JWT>}` where JWT carries `worker_slug` (from terminal-key), TTL 60s, single-use (own JTI tracked). Required header on `/msg/<id>/ratify_decision`. **The private key never leaves the SessionStart hook process memory; injected text in tool output cannot forge signatures.** |

## 4.1 Topic→tier classification (C2 — anti-downgrade; NC1 — fail-direction flipped V0.3.3)

**Why:** without classification, sender freely declares `tier_required`. Architect Critical C2: a B-code (authority=0) can post `kind: ratify_required, tier_required: 'B'` on a question that should be `'A'`. AH2 (level 1) then passes auth check at §3. Authority gate becomes theatrical.

**Fix:** server-side validator runs in `POST /msg/<terminal>` middleware whenever `kind = 'ratify_required'`. Looks up `topic` prefix in `_ops/processes/tier-classification.yml` (vault, owned by AI Head A) BEFORE inserting. Rejects with HTTP 400 if sender's declared `tier_required` < classified tier.

**V0.3.3 fail-direction (NC1):** default flipped from `director_only` → `B`. Reasoning: V0.3.2's `director_only` default would have blocked legit Cortex/PR ratify_required traffic on cold start (Tier-B autonomy lane dead until AI Head A manually extended YAML). Flipping to `B` means most fleet traffic flows; only the explicitly-tagged high-tier prefixes (capital-call, kill-criteria, gold-lock) require A or director_only. AI Head A is responsible for adding new high-tier topic prefixes as they emerge.

**Classification YAML (seed expanded V0.3.3 — covers all topic prefixes the brief itself uses):**

```yaml
# _ops/processes/tier-classification.yml
# Mapping: topic-prefix → minimum tier_required for any ratify_required on that topic.
# Default for unmatched prefixes: B (NC1: V0.3.3 flipped from director_only to permissive
# default; high-tier prefixes must be EXPLICITLY tagged below).

classifications:
  # Cortex routine traffic — Tier B
  - topic_prefix: "cortex/*/dispatch/"        # cortex dispatches
    min_tier: B
  - topic_prefix: "cortex/*/cycle-phase/"     # phase progression
    min_tier: B
  - topic_prefix: "cortex/*/cycle-id/"        # cycle-id tagging (free-form per-cycle)
    min_tier: B
  - topic_prefix: "cortex/*/sense/"           # Phase 1 sense outputs
    min_tier: B
  - topic_prefix: "cortex/*/reason/"          # Phase 3 reasoning outputs
    min_tier: B

  # PR / build-flow traffic — Tier B
  - topic_prefix: "pr-*/cascade/"             # PR cascade events
    min_tier: B
  - topic_prefix: "pr-*/review/"              # PR review events
    min_tier: B

  # Lifecycle / observability — Tier B (H6 audit emits land here)
  - topic_prefix: "lifecycle/restart"         # force_fresh_context SIGTERM emits
    min_tier: B
  - topic_prefix: "lifecycle/yaml-refresh-failed"  # NH1 keep-last-good audit
    min_tier: B
  - topic_prefix: "lifecycle/"                # broad fallback for other lifecycle events
    min_tier: B

  # Capital / commercial — Tier A (AI Head A or higher)
  - topic_prefix: "cortex/*/capital-call/"    # capital flow decisions
    min_tier: A
  - topic_prefix: "cortex/*/term-sheet/"      # term-sheet decisions
    min_tier: A
  - topic_prefix: "cortex/*/financing/"       # financing-structure decisions
    min_tier: A

  # High-stakes / strategic — director_only
  - topic_prefix: "cortex/*/kill-criteria/"   # project kill
    min_tier: director_only
  - topic_prefix: "cortex/*/gold-lock/"       # config GOLD lock
    min_tier: director_only
  - topic_prefix: "cortex/*/strategy/"        # strategic pivots
    min_tier: director_only

default_tier: B  # NC1 (V0.3.3): permissive default; high-tier must be explicitly tagged above
```

**Behavior:**
- Validator runs at INSERT time in `POST /msg/<terminal>` for `kind=ratify_required` (NOT only at `ratify_decision` — by then it's too late to reject).
- `POST /msg/<terminal>` returns HTTP 400 with `{error: "tier_below_classification", classified_tier: "A", declared_tier: "B"}` if declared < classified.
- Glob matching against `topic_prefix`. Multiple matches → take the highest-tier match (most restrictive wins).
- No match → `default_tier` (B per V0.3.3). Lower-than-default declared tier still rejects (you can't post `tier_required` lower than the classification ceiling).
- YAML loaded into module-level dict at process start; refreshed by 60s background task (H2 pattern). NH1 failure semantics: parse failure → keep last-good values, emit `lifecycle/yaml-refresh-failed`, dashboard counter increments.
- **M-A1 V0.3.4 + M-A5 V0.3.5 — default_tier provenance:** the YAML's `default_tier: B` field is the SOURCE; on process start, daemon loads it into a module-level constant `DEFAULT_TIER`. On YAML refresh failure (running daemon), NH1 keep-last-good extends to this constant — daemon retains the last-good value (NEVER falls to a hard-coded value or unset state) and continues running. **At process start with no in-memory last-good (M-A5 V0.3.5 disambiguation):** if the YAML cannot be parsed at process start, daemon refuses to start (loud failure beats silent wrong default). This does not conflict with NH1 "daemon never aborts on YAML failure" — NH1 covers the running-daemon refresh path; M-A1/M-A5 covers the cold-start-no-prior-state path. Two distinct scenarios; both spec'd.
- AI Head A maintains the YAML via vault PR (separate scope; queued for after V0.3.3 dispatch).

**`kind: ratify_required` semantics (Research 1 Steal #1, LangGraph `interrupt` pattern):**
- Sender posts a message with `kind: ratify_required` AND blocks its own thread on the recipient's `ratify_decision`.
- Recipient (canonically Director, per open Q below) posts a `ratify_decision` message with `parent_id: <ratify_required_id>` and `body: approve|reject + rationale`.
- Sender's thread unblocks on receipt of `ratify_decision`. This is the LangGraph `interrupt()` primitive transposed to the Brisen Lab bus.

---

## 5. Wake mechanism — class-aware (Decision #3)

| Worker class | Wake trigger | Notes |
|---|---|---|
| **tmux-backed terminals** (b1-b5, possibly architect post-carve-out) | Daemon does `tmux send-keys -t <terminal> '📨 inbox: <topic> <kind> from <from_terminal>' Enter` ONLY for `kind: dispatch` messages. **C3:** sets `wake_attempted_at` on tmux exit 0 — does NOT confirm delivery (paused/stopped pane returns success). Authoritative delivery = `acknowledged_at`, set when worker drains via `/msg/<id>/ack` or worker UPDATE on next turn boundary. | Confirm with Terminal AI Head A whether tmux is the actual harness or only the convention; if not tmux-backed, replace with named-pipe + UserPromptSubmit hook drain. |
| **Non-tmux Claude Code** (lead, deputy) | `SessionStart` hook (already shipped for V1 Lab observation, PR #149) extends to drain inbox at every turn-boundary via `UserPromptSubmit` hook combo. Drain calls `POST /msg/<id>/ack` for each consumed message (NM3: not direct DB write). | Drain on EVERY turn boundary; not just at session start. SessionStart hook ALSO generates ed25519 keypair + registers via `POST /auth/register-session-pubkey` (H7 / NC2). |
| **Cowork (Claude.ai App)** | Baker MCP tool `baker_inbox_read` called on session-open by MCP server's session-init hook; Director can also nudge manually | Auto-poll at session-open; on-demand via tool call thereafter. No long-lived connection. |
| **Cortex** | Bus reads happen at Phase 1 (sense) of every cycle; no separate wake — Cortex is always-running | `exclude_self=true` filter prevents cycle pollution (Decision #4). |

**Critical wake-mechanism rule (per Research 1 §Tier-4 Prompt 2 implication 5):** the `BRISEN_LAB_V2_ENABLED` flag check happens at **every wake-mechanism call site**, not just at daemon-start. If a worker is mid-cycle when the flag flips, the next wake call must check and abort. (Replit July 2025 freeze-flag-ignored lesson; H2 below.)

## 5.1 Context-renewal lifecycle (Hermes-pattern — V0.3 Amendment 2)

Director ratified option (c) hybrid 2026-05-02 PM. Token-pressure is the **default** lifecycle; a per-brief `force_fresh_context` flag overrides for class-change dispatches.

### Default — token-pressure 4-state machine

Each worker session lives across multiple briefs UNTIL a token-pressure threshold is hit. The 4 states (daemon-side state machine):

| State | Condition | Action |
|---|---|---|
| `green` | session tokens < 60% of context window | continue; deliver next brief into running session |
| `yellow` | session tokens 60–80% | continue; deliver next brief; emit warning to Lab |
| `orange` | session tokens 80–95% | finish current brief; SIGTERM after `acknowledged_at` set; restart fresh for next dispatch |
| `red` | session tokens ≥ 95% | SIGTERM immediately; restart fresh; deliver pending brief into new session |

Daemon supervisor reads a per-worker token-counter (already required by H3 OS-level ceiling); the same counter drives this state machine. No new instrumentation — reuse H3's wrapper.

### Override — `force_fresh_context: true` (brief frontmatter)

Brief metadata schema gains one optional field:

```yaml
# in briefs/_tasks/CODE_<N>_PENDING.md frontmatter
force_fresh_context: true   # optional, default false
```

Behavior (C4 — two-phase shutdown to eliminate mid-tool-call race; NC3 — idle signal source):
- `force_fresh_context: false` (default) → daemon follows token-pressure 4-state machine; session flows across briefs until threshold.
- `force_fresh_context: true` → **two-phase shutdown:**
  1. **Phase 1 — wait for idle.** Daemon polls worker activity. **NC3 idle definition (V0.3.3):** primary signal — wrapper exposes `/state` Unix-domain-socket endpoint at `/tmp/baker-wrapper-<worker_slug>.sock` reporting `{streaming: bool, tool_call_in_flight: bool, last_activity_ts: float}`; idle = `streaming==false AND tool_call_in_flight==false AND (now - last_activity_ts) >= 30s`. Fallback signal — if wrapper IPC unavailable, daemon uses no-wrapper-observed-activity for 30s threshold (raised from 5s in V0.3.2 to tolerate extended-thinking gaps + LLM-streaming pauses, both routinely 5–30s). Once idle: SIGTERM. (Drain-friendly; mid-`git push` or mid-PG-write completes; mid-thinking-block does NOT trigger false SIGTERM.)
  2. **Phase 2 — drain timeout.** If worker not idle within 60s of `force_fresh_context` brief arrival, SIGKILL. Logs forced-kill reason + last-known wrapper state to `_ops/incidents/forced-kill-<ts>.md` for Director audit.
  Worker restarts; SessionStart hook (PR #149, merged 2026-05-02) reads the new brief in fresh context AND generates a fresh ed25519 keypair (H7 / NC2) registered via `POST /auth/register-session-pubkey`.

H6 — audit trail: every Phase 1 SIGTERM (and every Phase 2 SIGKILL) emits `kind: broadcast, topic: lifecycle/restart, body: {worker, reason, drain_duration_ms}` to the bus BEFORE kill. Cheap; closes the audit gap (otherwise fleet quality regressions are hard to attribute).

**H-A3 (V0.3.4) + H-A4 atomicity (V0.3.5) — session-key expiry coupling:** the daemon executes both operations inside a SINGLE PG transaction:

```python
async with db.transaction():
    await db.execute(
        "UPDATE brisen_lab_session_keys SET expired_at = NOW() "
        "WHERE worker_slug = $1 AND expired_at IS NULL",
        restarting_worker
    )
    await db.execute(
        "INSERT INTO brisen_lab_msg (kind, topic, from_terminal, to_terminals, body, tier_required) "
        "VALUES ('broadcast', 'lifecycle/restart', 'daemon', ARRAY['*'], $1, 'B')",
        json.dumps({"worker": restarting_worker, "reason": reason, "drain_duration_ms": drain_ms})
    )
    # transaction commits both rows atomically OR neither
```

This closes the architect pass-4 H-A4 atomicity gap: emit-first-UPDATE-fails / UPDATE-first-emit-fails / daemon-dies-between are all impossible because both ops commit or neither does. On commit failure (rare — transient PG error), daemon logs the failure and the 24h sweep cleans up the stale pubkey row. The 24h sweep is documented as the sole backstop; no separate recovery path needed.

This closes the up-to-24h pubkey-validity window on worker crashes (architect pass-3 H-A3). The 24h sweep is retained as the fallback for OS-level kills that bypass the daemon's audit path entirely (e.g., Render container crash before the transaction can run).

**When to set the flag:** class-change dispatches where the worker's mental model needs to fully reset. Example: switching B1 from a Cortex-matter financial-modeling brief to a Lab UI styling brief — different vocabularies, different constraints, prior-session context becomes noise.

**Director-facing UX:** AI Head A drafts the brief and sets the flag in frontmatter when warranted. Dispatch flow handles the rest. Director never sees the renewal — invisible plumbing. No terminal hopping required.

### Interaction with H2 kill-switch

`force_fresh_context` SIGTERMs only ONE worker (the recipient). H2 `BRISEN_LAB_V2_ENABLED=false` SIGTERMs ALL workers. Same OS primitive; different scope. They do not conflict — H2 is fleet-level emergency stop; Hermes-pattern is per-dispatch lifecycle. **M3 incident dump:** when H2 flag flips OFF, daemon writes `_ops/incidents/lab-freeze-<ts>.md` listing all rows `WHERE acknowledged_at IS NULL AND deleted_at IS NULL` so Director can manually relay the in-flight dispatches via paste-block (AC6 fallback).

---

## 6. §Production Hardening — 6 MANDATORY requirements

ALL six are gates for `/security-review` to pass. Each is forced by a specific production incident from `wiki/research/2026-05-02-multi-agent-war-stories.md`. NONE are negotiable.

### H1 — Per-worker scoped 1Password vaults

- Each worker (`cowork-ah1`, `b1`, `b2`, `b3`, `b4`, `architect`, `lead`, `deputy`, `cortex`) has its OWN 1Password vault.
- No shared vault. No env-var creds in `~/.zshrc` or shell profiles.
- Credentials surface only via `op run --` execution wrapper at task start.
- Vaults scoped to least-privilege: no broad-scope cloud-provider tokens (Render, Railway, AWS root) unless role explicitly requires.
- **Lesson:** Cursor/PocketOS 9-second prod-DB delete via broad-scope Railway CLI token (Apr 2026). See `war-stories §1`.

### H2 — Kill-switch as process-level SIGTERM, not flag file

- `BRISEN_LAB_V2_ENABLED=false` triggers daemon supervisor (Render service definition / local daemon parent process) to send SIGTERM to all workers.
- Agents must be **physically unable** to ignore the freeze — kill is at OS-process boundary, not at prompt-engineering boundary.
- Reinforced by mid-cycle flag check at every wake-mechanism call site (per §5 critical rule).
- **Lesson:** Replit Agent July 2025 freeze-flag-ignored, deleted prod DB and faked recovery data. See `war-stories §2`.

### H3 — Wrapper-enforced token-rate ceiling + egress-firewall guard (C5 honesty rewrite)

**Honesty correction (V0.3.2):** V0.3.1 implied cgroups enforce token-rate ceilings. They don't. cgroups limit CPU/memory/IO, NOT network egress per-rate. The actual enforcement is in a **wrapper layer** that wraps Anthropic SDK calls. Without an egress-firewall guard, a subagent that bypasses the wrapper (e.g., spawns its own `anthropic.Anthropic()` client) escapes rate-limit enforcement — exactly the "49 sub-agents at 887K tok/min" attack the H3 lesson warns about.

**Enforcement (two layers):**
1. **Wrapper layer (`baker_wrapper.py`):** all Anthropic SDK calls go through this wrapper. Wrapper enforces:
   - **Per-worker:** `MAX_TOKENS_PER_MIN` and `MAX_USD_PER_HOUR` (defaults: b-codes 100K tok/min + $5/hr; cortex 200K tok/min + $20/hr; cowork 50K tok/min + $2/hr; AI Heads 75K tok/min + $3/hr).
   - **Fleet-aggregate:** `MAX_FLEET_USD_PER_DAY` (default $200/day) — auto-pauses ALL workers when ceiling hit; Director manually un-pauses.
   - On limit hit: wrapper rejects the call (returns rate-limit-style error to the worker). Worker handles fail gracefully or terminates per H4.
2. **Egress firewall (Render service / local daemon):** OS-level firewall rule blocks outbound traffic to `api.anthropic.com` for any process not running under the wrapper's UID. Subagents either (a) inherit wrapper UID via `op run --` execution wrapper (subject to limits) OR (b) cannot reach Anthropic at all (network rejection at egress). No third path.

**Acceptance test:** spawn a Python subprocess from inside a worker that imports `anthropic` directly (bypassing wrapper) and attempts a chat completion. Expect: connection refused / DNS rejection. If the call succeeds, H3 is broken.

- **Lesson:** AICosts.ai (Jul 2025 post; principle re-anchored Q1 2026) — documented incident: 49 sub-agents running 887K tokens/min for 2.5h via fan-out. The fan-out succeeded specifically because subagents bypassed the rate-limit instrumentation. Source: https://www.aicosts.ai/blog/claude-code-subagent-cost-explosion-887k-tokens-minute-crisis. See `war-stories §3` (vault PR pending parallel update).

### H4 — Session-failure-rate watchdog

- Each worker emits a `failure_count` metric to Lab's Postgres event store on every tool-call failure.
- Daemon supervisor monitors per-worker counters; auto-kills + restarts with fresh context at **N consecutive failures** (default N=10; configurable per role: b-codes lenient N=15; cortex strict N=5 because each call expensive).
- Counter resets on every successful completion.
- Watchdog metric exposed in Brisen Lab dashboard for Director audit-only oversight.
- **Lesson:** Anthropic public engineering postmortem (2026-04-23) — Claude Code prompt + caching changes degraded silently in production; the consecutive-failure quality-drop pattern was invisible to offline evals and only surfaced via runtime watchdog telemetry. Source: https://www.anthropic.com/engineering/april-23-postmortem. See `war-stories §4` (vault PR pending parallel update).

### H5 — `.claude/settings*.json` in global gitignore + npmignore; 1Password CLI refs only

- Pre-commit hook validates: every value in `env`, `headers`, or auth-shaped fields must be either a literal placeholder OR a `op://VAULT/ITEM/FIELD` reference. Inline secret match → block commit.
- Global `.gitignore` and global `.npmignore` lines added at repo init: `.claude/settings.local.json` and `.claude/settings.json`.
- Daemon supervisor refuses to start if either ignore-file is missing the entries.
- Workers consume credentials via `op run --` wrapper — credentials resolved at process start; never written to disk in plaintext.
- **Lesson:** Lakera research (Elliot W., Staff AI Security Researcher, 2026-04-22) + Check Point corroboration (Steve Giguere, 2026-04-23) — inline secrets via "allow always" persisted into `.claude/settings.local.json`; **428 of 46,500 npm packages** contained the file; **33 files across 30 packages** held live credentials exposed via npm publish. Sources: https://www.lakera.ai/blog/your-ai-coding-assistant-just-shipped-your-api-keys + https://securitybrief.asia/story/claude-code-can-leak-secrets-in-public-npm-packages. See `war-stories §5` (vault PR pending parallel update).

### H6 — Per-MCP trust domain

- Each MCP integration (Linear, GitHub, Notion, Google Workspace, Slack, Fireflies, Dropbox, ClickUp, Todoist, Baker) authenticates as its **own scoped identity** with **least-privilege OAuth scopes**.
- Each MCP's tokens stored in its own 1Password sub-item (linked to worker vault from H1).
- OAuth scopes documented per integration in `.claude/mcp-scopes.md` and audited monthly.
- MCP daemon enforces a "trust boundary" — Linear MCP cannot read or write to GitHub MCP's token, etc.
- New MCP addition requires explicit Director ratification + scope documentation.
- **Lesson:** Vercel / Context.ai cross-pivot (Apr 2026) — compromised 3rd-party AI tool used as pivot to env vars. See `war-stories §6`.

### H7 — Subagent-impersonation prevention via human-confirmation token (V0.3.2 NEW)

**Why:** architect-reviewer pass 1 surfaced the impersonation hole — a B-code (authority=0) cannot directly post `kind: ratify_decision` (auth check rejects), but injected output reaching a higher-authority worker's session (e.g., lead, authority=2) could be read by a `SessionStart` or `UserPromptSubmit` hook that auto-posts on the lead's behalf. Result: B-code obtains a ratify_decision it shouldn't have. The Q1 authority gate becomes theatrical — auth rules exist on paper, but anyone in the fleet can bypass them by writing the right injected text.

**Mechanism (V0.3.3 — concrete enforcement primitive per architect-reviewer pass 2 NC2):**

The V0.3.2 spec said the token endpoint was "callable ONLY from UserPromptSubmit hook context" without specifying HOW the daemon could distinguish a hook-origin call from any other call carrying the worker's terminal-key. That was theatrical — a B-code's tool subprocess could call the endpoint with the worker's terminal-key. V0.3.3 closes the gap with public-key crypto bound to a per-session keypair held by the SessionStart hook process.

1. **Session keypair generation (SessionStart hook, ONCE per session):**
   - Hook generates an ed25519 keypair using OS-level CSPRNG.
   - Hook posts `POST /auth/register-session-pubkey` with `{pubkey, terminal_slug}` and `terminal-key` header.
   - Daemon stores `{session_id, worker_slug, pubkey, registered_at}`. PK on `session_id`; re-registration → HTTP 409.
   - Daemon returns `{session_id}`. Hook keeps `session_id` + private key in process memory; never written to disk.

2. **Human-confirmation token issuance (UserPromptSubmit hook fires on actual human keystroke):**
   - Hook constructs `payload = {worker_slug, session_id, prompt_hash, ts, nonce}` where `prompt_hash = sha256(<human's submitted prompt text>)` and `nonce = random_uuid()`.
   - Hook signs: `signature = ed25519_sign(session_privkey, payload)`.
   - Hook posts `POST /auth/human-confirmation` with `{session_id, payload, signature}`.
   - Daemon validates: (a) signature against registered pubkey for `session_id`; (b) `ts` within 60s; (c) `nonce` not previously consumed (60s LRU). Any failure → HTTP 403.
   - On valid: daemon returns `{token: <JWT>}`. JWT carries `{worker_slug, jti, iat, exp}`; TTL 60s; signed with daemon key.

3. **Ratify-decision enforcement:**
   - `POST /msg/<id>/ratify_decision` requires `X-Human-Confirmation-Token` header.
   - Daemon validates: signature, freshness (≤60s), `jti` not previously consumed (60s LRU).
   - **NH2 (V0.3.3):** also validates `token.worker_slug == caller's terminal-key worker_slug`. Defends the cross-worker forwarding attack (b1 fetches its own token, then forwards to lead with lead's terminal-key — token's worker_slug=b1 ≠ caller's worker_slug=lead → HTTP 403).
   - Missing/expired/replayed/cross-worker → HTTP 403.

**Why the primitive defends the impersonation:**
- Private key lives only in the SessionStart hook's process memory; never persisted.
- Default OS process isolation prevents read by other processes at the worker's UID (`ptrace` blocked without privileges; private memory page).
- Injected text in tool output goes through Claude's response pipeline — does NOT trigger UserPromptSubmit hook firing. Tool calls bypass UserPromptSubmit entirely.
- Even if a B-code subprocess hits `/auth/human-confirmation` with a forged-looking payload, it cannot produce a valid signature without the private key. Server signature check fails.
- Daemon's pubkey registry is bound to `session_id`; a new session always means new keypair + fresh registration.

**Daemon-side keys:**
- Daemon-signed JWT key stored in 1Password (per H1 worker vault scoping; daemon vault). Rotated quarterly.
- Per-session pubkeys stored in PG (`brisen_lab_session_keys` table). Rows soft-expire (V0.3.4 H-A3): primary path = `lifecycle/restart` audit handler UPDATE; fallback = 24h sweep for crashes that bypass the audit path.

**L-A2 V0.3.4 + L-A3 V0.3.5 — nonce/jti LRU sizing + lifetime:** the 60s replay-protection LRUs (one for `nonce` on `/auth/human-confirmation`; one for `jti` on `/msg/<id>/ratify_decision`) live in daemon process memory (Python `collections.OrderedDict` capped at 10K entries each — peak fleet load is ~480 entries (8 ratify/min × 60s); cap chosen for misbehaving-client safety, not steady-state sizing — covers pathological burst from a buggy client hitting `/auth/human-confirmation` in a tight loop). On daemon restart, both LRUs clear. Replay-protection window opens for ≤60s post-deploy. Documented as known-and-accepted property — Tier-B authorization gate; cost of distributed nonce store (Redis) > cost of 60s replay window after a controlled deploy.

**Acceptance test (extends A21):**
- attempt to post `ratify_decision` with no `X-Human-Confirmation-Token` → HTTP 403.
- attempt with token issued for `b1` but caller's terminal-key is lead's → HTTP 403 (NH2 cross-worker reject).
- attempt with valid token, immediately replay → first OK; second HTTP 403 (jti consumed).
- attempt with token >60s old → HTTP 403 (expired).
- attempt to call `/auth/human-confirmation` from a B-code's tool subprocess (no hook keypair access) → forged signature → HTTP 403 (signature invalid).
- attempt to call `/auth/register-session-pubkey` twice with same `session_id` → second HTTP 409 (single registration per session).
- valid path — human types in lead terminal, UserPromptSubmit hook signs + exchanges for token, ratify_decision posts → HTTP 200.

- **Lesson:** architect-reviewer pass 1 (2026-05-03, Brisen Lab V2 brief review) surfaced the impersonation gate as the highest-leverage High finding. Promoted to Critical hardening req per Director ratification 2026-05-03. Cousin pattern: Lesson #44 (`/write-brief` REVIEW catches what informal exploration misses) — H7 is the architecture-review analog: structured review catches what brief-author + AH2 verification both missed.

---

## 7. Acceptance criteria (shipped-when-true)

A1. New routes implemented + tested: `POST /msg/<terminal>`, `GET /msg/<terminal>`, `GET /event/<id>/full`, `DELETE /msg/<id>`, `POST /msg/<id>/ack`, `POST /msg/<id>/ratify_decision`, `GET /api/v2/matters`, `GET /api/v2/terminals`, `POST /auth/register-session-pubkey` (V0.3.3 H7), `POST /auth/human-confirmation` (V0.3.3 H7).
A2. Schema migrations applied to Neon Postgres in this order (L-A1 V0.3.4): (1) `brisen_lab_msg` (incl. `parent_id` C1, `wake_attempted_at` C3 rename, `tier_required` Q1, `kind` enum without bare 'ratify' M5; indexes incl. `idx_msg_open_ratifies` H-A2 V0.3.4), (2) `brisen_lab_worker_authority` (Q1), (3) `brisen_lab_session_keys` (V0.3.3 H7/NC2; FK depends on (2); `session_id` server-issued via `gen_random_uuid()` per M-A2 V0.3.4). Idempotent-wake columns (`wake_attempted_at`, `acknowledged_at`) populated in tests.
A3. Wake mechanism class-aware: dispatch-class wake fires for tmux + SessionStart + Cowork-MCP-poll; other classes drain on next turn boundary.
A4. Cortex peer + self-read filter functional; Cortex Phase 2 reads exclude its own broadcasts.
A5. Director escalation policy filter live: only `kind: ratify_required` and explicit `to: [director]` messages push.
A6. Brisen Lab UI gains `cowork` card; threading groups events by `thread_id`.
A7. `baker_inbox_post` + `baker_inbox_read` MCP tools added to Baker MCP server; Cowork session-open triggers auto-read.
A8. Soft-delete with 5-min sender window + always-Director authority works.
A9. Retention-forever policy verified (no automatic hard-delete; soft-delete only).
A10. Feature flag `BRISEN_LAB_V2_ENABLED` triggers SIGTERM at supervisor level when flipped to `false` (H2 verified end-to-end).
A11. **§Production Hardening H1–H7 ALL pass `/security-review`.** This is a hard gate. (V0.3.2: H7 added — subagent-impersonation prevention via human-confirmation token.)
A12. Paste-block-via-Director fallback works when flag OFF or worker unreachable (AC6).
A13. **OpenTelemetry GenAI Semantic Conventions spans emitted (RATIFIED V0.3 — mandatory, no defer).** Spans on `POST /msg` + each wake-mechanism call + `POST /msg/<id>/ratify_decision`. Direct feed into trust-thermostat ritual (Director's tracking). 1-day cost vs 2-day V3 retrofit. Reference: Research 1 Steal #3.

### Context-renewal hybrid (V0.3 Amendment 2)

A14. **Context-renewal hybrid behavior verified (Hermes-pattern, §5.1):**
  - Test (a): dispatch a brief WITHOUT `force_fresh_context` → daemon follows token-pressure 4-state machine; session continues (pressure permitting); manual test passes for green/yellow path.
  - Test (b): dispatch a brief WITH `force_fresh_context: true` → daemon waits for worker idle per §5.1 (preferred: wrapper IPC `/state` reports `streaming==false AND tool_call_in_flight==false AND last_activity_ts ≥ 30s`; fallback: 30s no-wrapper-observed-activity), then SIGTERMs; worker restarts; SessionStart hook reads new brief in fresh context AND generates a fresh ed25519 keypair (H7/NC2). Manual test passes. (V0.3.4 H-A1: text rot from V0.3.3 §5.1 fix corrected — was "5s OR awaiting input".)
  - Test (c): dispatch DURING `red` state without flag → daemon waits for idle, SIGTERMs, delivers into new session; manual test passes.
  - **Test (d) — C4 mid-tool-call drain:** worker mid-`git push` when `force_fresh_context` brief lands → daemon defers SIGTERM until push completes (verified by checking `acknowledged_at` on prior dispatch is set BEFORE the SIGTERM lifecycle event); manual test passes.
  - **Test (e) — drain timeout:** worker stuck in tool call for >60s → daemon SIGKILLs after 60s, writes `_ops/incidents/forced-kill-<ts>.md`; manual test passes.
  - **Test (f) — H6 audit emit:** every Phase 1 SIGTERM and Phase 2 SIGKILL emits `kind: broadcast, topic: lifecycle/restart` to bus before kill; verify bus row exists for each test (a)–(e).
  - **Test (g) — H-A4 V0.3.5 atomicity:** after `force_fresh_context` SIGTERM, verify `brisen_lab_session_keys.expired_at` is set within the SAME PG transaction as the `lifecycle/restart` row INSERT (i.e., both rows share the same `xmin` / commit timestamp). Inject a transient PG error during the transaction → verify NEITHER op commits (no orphan expired_at without broadcast; no orphan broadcast without expired_at).
  - Token-counter for the 4-state machine reuses H3's wrapper — no new instrumentation.

### Component 6 — Dashboard 2-view (V0.3 fold-in)

A15. **2-view layout shipped:** left-nav with two views — "Production & Lab" and "Business". Default view = Production & Lab. Active view persists in URL hash + localStorage.
A16. **View 1 (Production & Lab):** 6 terminal cards (lead, deputy, b1, b2, b3, b4) + Cortex card + Cowork card. Terminal cards show: latest event preview (≤140 chars), last `acknowledged_at`, current `failure_count` (H4 watchdog). Cortex card shows: Director-consult flag (red banner when `kind: ratify_required` open), current cycle phase (1–6), cost so far this cycle, stuck-flag (no phase progression in 2 min). Cowork card shows: latest event, MCP poll status, `baker_inbox_read` / `baker_inbox_post` timestamps.
A17. **View 2 (Business):** matter cards rendered from `GET /api/v2/matters`. Status from vault `slugs.yml` partitions matters into "Active" (`status: active`) and "Development" (status NOT IN ('active','retired')). Active matters render in primary section; development matters in collapsible sub-section (default collapsed). Counts at build time — no hardcoded numbers.
A18. **Matter card spec — 5 fields:** (a) matter name + slug; (b) last cycle status (gold/pending/stuck — derived from `cortex_cycles.terminal_state` + `gold_status` flag in cortex-config); (c) cost MTD (sum `cortex_cycles.total_cost_usd` WHERE `started_at >= date_trunc('month', NOW())` AND `matter_slug = ?`); (d) active brief if any (slug from `cortex-roadmap-current.yml` `in_flight` or `queued` filtered by matter); (e) open Director-Qs count (`SELECT COUNT(*) FROM brisen_lab_msg WHERE topic LIKE 'cortex/<slug>/%' AND kind='ratify_required' AND acknowledged_at IS NULL LIMIT 200`).
A19. **`GET /api/v2/matters` data sourcing (H1 + H2 + NH1):**
  - DB sources: `cortex_cycles` + `cortex_phase_outputs` (Postgres) — read inside the request handler, single async query each.
  - Vault YAMLs: `_ops/processes/cortex-roadmap-current.yml` + `slugs.yml` + `_ops/processes/tier-classification.yml` — loaded into module-level dict at process start; refreshed by 60s background task (H2: NO filesystem read inside request handlers).
  - **NH1 background task failure semantics (V0.3.3 + M-A3 V0.3.4):** parse failure or filesystem error → keep last-good values in module dict; emit `kind: broadcast, topic: lifecycle/yaml-refresh-failed, body: {file, error, last_good_age_s}` to bus; increment `yaml_refresh_failure_count` metric exposed in dashboard (Brisen Lab UI). **Counter reset (M-A3):** counter resets to 0 on the first successful refresh after any failure. The 3-strike escalation triggers only on 3 consecutive failures with no intervening success. Three consecutive failures escalate to `kind: ratify_required, tier_required: B, to: [aihead-a]` so AH1 fixes the YAML. Daemon never aborts on YAML failure (silent stale > full Lab outage).
  - Cache: 60s in-process for the assembled response, with **single-flight `asyncio.Lock` per cache key** (H1: prevents stampede when N tabs hit a cold cache).
  - **No new tables for matter cards.** Director's amendment referenced "V-state files" — those are not a discrete artifact; B-code uses the 4 sources above and surfaces a Director-Q to AH1 if a 5th source proves needed during build. (Note: V0.3.3 adds `brisen_lab_session_keys` for H7 / NC2 — that's separate, for auth, not for matter data.)
A20. **Frontend volume budget:** matter card template matches the existing terminal-card visual hierarchy; line counts are advisory only (V0.3.1 said ~300–400; V0.3.2 drops the hard number per architect L2). CSS cache-bust `?v=N` on every static asset change (anti-pattern: no cache bust kills iOS PWA refresh).
A21. **H7 — Subagent-impersonation prevention verified (§6 H7 + NC2 + NH2 V0.3.3):**
  - Test (a): post `ratify_decision` with no `X-Human-Confirmation-Token` header → HTTP 403.
  - Test (b) **NH2 cross-worker reject:** post with token issued for `b1` but caller's terminal-key is `lead`'s → HTTP 403 (`token.worker_slug` ≠ caller's `worker_slug`).
  - Test (c): post with valid token, then replay same token within 60s → first OK, second HTTP 403 (jti consumed).
  - Test (d): post with token >60s old → HTTP 403 (expired).
  - Test (e) **NC2 forged-signature reject:** B-code subprocess hits `/auth/human-confirmation` with a forged-looking payload but no access to the SessionStart hook's private key → signature verification fails → HTTP 403. (Replaces V0.3.2 test (e) which was unimplementable as written.)
  - Test (f): valid path — human types in lead's terminal, UserPromptSubmit hook signs payload with session privkey, exchanges for token, ratify_decision posts → HTTP 200.
  - Test (g) **NC2 registration-uniqueness:** call `POST /auth/register-session-pubkey` twice with the same `session_id` → first 200, second HTTP 409 (one-time per session).
  - Test (h) **M-A4 V0.3.5 — client-provided-session_id rejection:** call `POST /auth/register-session-pubkey` with body `{pubkey, session_id: <client-uuid>}` → HTTP 400 (`error: client_session_id_forbidden`). Server-issued only.

---

## 8. Lane + sequence

1. ✅ **AH2 (Cowork)** — V0.2 authored 2026-05-02. Posted for AI Head A review.
2. ✅ **AI Head A review** — pre-Director sign-off; surfaced Q1+Q2 + OTel + Component 6 fold + verify-before-dispatch to Director.
3. ✅ **Director ratifies V0.2 + answers open Qs (2026-05-02 PM)** — see §9. Q1=(c), Q2=(b), OTel=INCLUDE, verify-before-dispatch=YES, DASHBOARD_2VIEW_1 fold=YES.
4. ✅ **AH1 V0.3 amend** — folds ratifications + Component 6 + Hermes-pattern (Amendment 2) into brief; deletes DASHBOARD_2VIEW_1 stub.
5. ✅ **Anchor verification (gate before B-code dispatch) — DONE 2026-05-02 PM.** AH2 ran the pass; all 3 original citations had attribution problems; Director ratified corrections in chat; brief patched V0.3 → V0.3.1 with new primary sources. See §0 V0.3.1 patch. Original tasked verification list (preserved for audit):
   - Wiz disclosure URL → corrected to Lakera (Elliot W., 2026-04-22) + Check Point corroboration
   - AICosts.ai $47K/72h figure → corrected to documented 49 sub-agents / 887K tokens/min / 2.5h (same article, Jul 2025)
   - Anthropic 1,279-session anchor → dropped specific number; re-anchored on Anthropic public April 23 postmortem
6. **AI Head A posts V0.3-final paste-block to Cowork** with verification confirmations attached.
7. **Director final OK on V0.3-final** → AI Head A dispatches to least-loaded B-code (per Lab mailbox state at dispatch time). Branch convention `b<N>/brisen-lab-v2-bridge-1`.
8. **B<N> builds** — schema migrations + endpoints + MCP tools + Brisen Lab UI updates (incl. Component 6) + Hermes-pattern + hardening implementation. Estimated effort: 3–4 days bus + 3–5 days Component 6 + ~1–2h Hermes spec ≈ ~2.5–3 weeks total.
9. **`/security-review` mandatory** — H1–H6 verified end-to-end; reviewer rotation per Lesson #52.
10. **Merge** — rebase + standard squash-merge to `main` (V0.3.3 / L3 fix: V0.3.2 erroneously specified `--force-with-lease`; force-push to `main` is globally forbidden per `~/.claude/CLAUDE.md` hard rules. Standard Baker convention is rebase + squash).
11. **Post-merge cutover** — `BRISEN_LAB_V2_ENABLED=true` after security-review pass; paste-block-via-Director continues as fallback (AC6).
12. **Carve-out backlog dispatch** — AI Head A queues remaining 3 carve-out briefs (`ARCHITECT_TERMINAL_1`, `TIER_B_AUTONOMY_1`, `SESSION_START_DIGEST_1`) in `cortex-roadmap-current.yml`.

---

## 9. Director ratifications (V0.3, 2026-05-02 PM)

Both V0.2 open questions ratified, plus OTel + verify-before-dispatch + Component 6 fold + Hermes-pattern (Amendment 2). Below: ratification logs preserved for audit traceability.

### Q1 — Who can post `kind: ratify_decision`? — RATIFIED (c) per-worker `ratify_authority_level`

**Director's choice (2026-05-02 PM):** option (c) — per-worker authority level encoded in DB; codified in `bank-model.md`.

**Reasoning (Director):** option (a) Director-only would have broken the Tier-B autonomy lane (decision #13, already ratified — separate carve-out `BRIEF_TIER_B_AUTONOMY_1.md`). Option (c) preserves #13 cleanly while keeping Director sole authority for ALL_TIERS.

**Codified defaults (mirror in `_ops/processes/bank-model.md` via separate vault PR):**

| Worker slug | `ratify_authority_level` | Scope |
|---|---|---|
| `director` | 3 (ALL_TIERS) | All — idea greenlight, Tier-B/C ratify, kill criteria |
| `cowork-ah1` | 2 (TIER_B_EXEC) | TIER_B execution ratify within Director-greenlit lanes (AI Head A — Cowork) |
| `lead` | 2 (TIER_B_EXEC) | TIER_B execution ratify within Director-greenlit lanes (AI Head A — Code terminal AH1) |
| `deputy` | 1 (TIER_B) | TIER_B for review-related ratifies (AH2) |
| `architect` | 1 (TIER_B) | TIER_B for brief reviews |
| `b1`–`b5` | 0 (NONE) | Implementation only |
| `cortex` | 0 (NONE) | Posts `ratify_required` upward; never decides |

**Implementation:** §3 schema adds `brisen_lab_worker_authority` table seeded with the above. `POST /msg/<id>/ratify_decision` middleware enforces `worker.ratify_authority_level >= parent_msg.tier_required` (parent message carries `tier_required` column; default `B`).

### Q2 — Thread visibility — RATIFIED (b) scoped to `to: [list]` + always-Director

**Director's choice (2026-05-02 PM):** option (b) — scoped to `to: [list]` participants + Director always included.

**Reasoning:** Cortex self-read filter (Decision #4) already requires per-recipient filtering; (a) all-terminals would have conflicted. `kind: broadcast` messages opt into all-terminal visibility via `to: [all]`, preserving broadcast as an explicit, intentional act rather than the default.

### Additional V0.3 ratifications

- **OTel:** INCLUDE in V2 (was "defer to V2.5 if time-pressed" in V0.2). Ratified mandatory; AC = A13.
- **Verify-before-dispatch:** AH2 (primary) verifies the 3 anchor citations (Wiz, AICosts.ai $47K/72h, Anthropic 1,279-session) before B-code dispatch. ~20–30 min. Fallback: AH1.
- **Component 6 fold-in:** DASHBOARD_2VIEW_1 absorbed; ETA +3–5 days. Spec at §4 endpoints + §7 A15–A20.
- **Amendment 2 — Hermes-pattern:** option (c) hybrid; default token-pressure 4-state + per-brief `force_fresh_context: true` override. Spec §5.1; AC = A14.

---

## 10. Anchors

- V0.1 source (this thread, AI Head A authored 2026-05-02)
- V0.1 scope notes: `baker-vault/_ops/ideas/2026-05-01-brisen-lab-msgbus-scope.md`
- Research 1: `baker-vault/wiki/research/2026-05-02-multi-agent-fleet-architectures.md`
- Research 2: `baker-vault/wiki/research/2026-05-02-multi-agent-war-stories.md`
- Existing Brisen Lab v1: `aihead/brief-brisen-lab-1-20260501` baker-master branch (Terminal AH1 authored 2026-05-01 ~00:00Z); live at https://brisen-lab.onrender.com
- SessionStart hook (PR #149, merged 2026-05-02 `7ad5e3e`) — `force_fresh_context` override leverages this hook for the renewal path
- Lesson #52 — `/security-review` mandatory for new auth surfaces
- Lesson #44 — `/write-brief` SOP catches what informal exploration misses (V0.3 amend ran the SOP)
- `feedback_paste_block_strict.md` — standing rule being amended with carve-out (AC6)
- `cortex-roadmap-current.yml` — entry renamed to `brief-brisen-lab-v2-bridge-1` post-Director-ratification
- `_ops/processes/bank-model.md` — receives separate vault PR codifying Q1 ratify_authority_level defaults table
- `_ops/processes/cortex-stage2-v1-tracker.md` — Step 30 first LIVE AO cycle remains separate (Director-consult gate, charter §4); Brisen Lab V2 unblocks but does not depend on it
- **V0.3.1 anchor primary sources (AH2-verified 2026-05-02 PM):**
  - https://www.lakera.ai/blog/your-ai-coding-assistant-just-shipped-your-api-keys (H5 primary)
  - https://securitybrief.asia/story/claude-code-can-leak-secrets-in-public-npm-packages (H5 corroboration)
  - https://www.aicosts.ai/blog/claude-code-subagent-cost-explosion-887k-tokens-minute-crisis (H3 primary)
  - https://www.anthropic.com/engineering/april-23-postmortem (H4 primary)
- **Follow-up vault PR (out of scope for V2_BRIDGE_1 build):** update `wiki/research/2026-05-02-multi-agent-war-stories.md` §1/§3/§4/§5 to mirror the V0.3.1 corrections. AI Head A queues this as a separate baker-vault PR after dispatch.

---

## 11. Carve-out brief stubs (one-paragraph each, co-located in same dir)

V0.3 update (2026-05-02): DASHBOARD_2VIEW_1 absorbed as Component 6; stub deleted. Remaining carve-outs:

- `BRIEF_ARCHITECT_TERMINAL_1.md`
- `BRIEF_TIER_B_AUTONOMY_1.md`
- `BRIEF_SESSION_START_DIGEST_1.md`

Each carve-out is a one-paragraph stub queueable into `cortex-roadmap-current.yml`; AI Head A handles the roadmap amendment in a separate paste-block.
