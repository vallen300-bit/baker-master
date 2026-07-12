# B1_bus_fleet_comms_audit_1 — Fleet Bus-Communications Audit (diagnose-only)

**Brief:** `briefs/_tasks/BUS_FLEET_COMMS_AUDIT_1.md` (dispatch #9165, Director-directed 2026-07-12).
**Scope addition:** #9180 (Director-reviewed via cowork-ah1 #9179; folded as report-framing, no brief amendment) — added the CAN-do vs MUST-do duty dimension, role-shaped N/A discipline, and single-policy framing for wildcard backlog.
**Author:** b1. **Date:** 2026-07-12. **Class:** diagnose-only, READ-ONLY (no fixes; no bus writes beyond self-addressed test acks/posts).
**Harness-V2:** N/A per brief (audit; output is findings + prioritized fix list for lead ratification).
**Rev:** rev2 (rev1 shipped PR #526; rev2 folds scope-addition #9180 + the live body-read finding F0).

## Method + evidence base

- Live daemon `origin/main` @ `8e81029` (brisen-lab), production `https://brisen-lab.onrender.com`.
- Live per-seat telemetry: `GET /api/v2/terminals` (director key) — 41 cards.
- Own-seat live surface test (b1): `GET /msg/b1` list read; `POST /msg/9165/ack` → 200; `bus_post.sh` #9176/#9182 → 200.
- Static route inspection (Explore fan-out): `app.py bus.py authz.py auth_lab.py db.py lifecycle.py agent_identity_generated.py` @8e81029.
- Duty extraction (Explore fan-out): 21 orientation.md files under `~/baker-vault/_ops/agents/`.
- MCP identity test: `baker_inbox_read(terminal=b1)` → **HTTP 403 `reader_slug_mismatch`** (reproduced live).
- **Live self-incident:** the audit's own read-surface defect (F0) nearly caused me to miss scope addition #9180 — captured as primary evidence.

**Coverage: 100% of the 41 registry/card slugs** (I/O matrix). Duty matrix is by **role-class** (duties are role-shaped per #9180-item-2), every seat mapped to a class. N/A rows carry reasons. Unverifiable items flagged in §Coverage gaps.

---

## §0 HEADLINE — the read surface is body-blind (live self-incident)

The single most consequential finding, because it bit this audit in real time:

- `GET /msg/{slug}` (the documented per-seat inbox read) returns a field named **`body_preview`**, **not** `body`. There is **no `body` field** in the projection.
- **`GET /msg/{id}` is not a route.** A numeric id is parsed as `/msg/{terminal="<id>"}` and returns `{"detail": …}`. There is **no full-body single-message retrieval surface anywhere.**
- `body_preview` is capped (daemon caps preview at 8KB/row per the MCP tool contract). Under 8KB the preview is the whole body; over 8KB it silently truncates with no full-body fallback.

**Impact (proven):** my first three reads of lead's replies checked `body` → got `None` → I logged #9177/#9180 as "empty." They were not: #9177 (431 chars) confirmed the queue-brief closure; **#9180 (805 chars) was a Director-reviewed SCOPE ADDITION to this very brief.** A seat (or tool) that reads `body` instead of `body_preview` is **totally blind** to message content — not degraded, blind. This is the ARM "no body-read surface" incident class (brief says fixed #9164 / vault PR #164); the fix added a **preview** field under a **different name** and **no full-body route**, so the blindness persists for any reader keyed on `body`. Sev **P1** (near-miss of a Director-reviewed instruction; general fleet body-blindness).

---

## §1 Seat I/O matrix — CAN-do vs MUST-do

**CAN-do** columns (capability): read / ack / post / wake. **MUST-do** column (duty profile, role-shaped — source: 21 orientation files). A cell mismatch **in either direction** is a finding: CAN-but-must-not = over-capability; MUST-but-cannot = broken duty.

CAN-do determination is by runtime + key mechanism (`auth_lab.resolve_terminal_key`, `authz.py:161`); the b1 end-to-end test proves the terminal-seat path. Per #9180-item-2, missing a capability a role's duty never needs is **N/A(reason)**, not BROKEN.

### 1a. CAN-do capability (41 slugs, 100%)

| slug | runtime | read | ack | post | wake |
|---|---|---|---|---|---|
| lead | terminal-claude | OK | OK | OK | OK |
| deputy | terminal-claude | OK | OK | OK | OK⚠tel |
| deputy-codex | terminal-codex | OK | OK | OK | OK⚠tel |
| aid | terminal-claude | OK | OK | OK | OK |
| b1 | terminal-claude | OK✓ | OK✓ | OK✓ | OK⚠tel |
| b2 | terminal-claude | OK | OK | OK | OK⚠tel |
| b3 | terminal-claude | OK | OK | OK | OK⚠tel |
| b4 | terminal-claude | OK | OK | OK | OK⚠tel |
| researcher | terminal-claude | OK | **BROKEN**(F2) | OK | OK |
| codex | terminal-codex | OK | OK | OK | OK |
| codex-arch | app-codex | OK | OK | OK | N-A(app-resident) |
| clerk | headless-qwen3 | OK | OK | OK | N-A(headless, no session) |
| clerk-haiku | terminal-claude-haiku | OK | OK | OK | OK(planned) |
| russo-ai | terminal-claude | OK | OK | OK | OK |
| deep55 | terminal-openai-raw | OK | OK | OK | OK(planned) |
| ben | app-claude | OK | OK | OK | N-A(app-resident) |
| librarian | terminal-claude-sonnet | OK | OK | OK | OK |
| arm | terminal-claude-sonnet | OK | OK | OK | OK |
| hag-desk | terminal-claude | OK | OK | OK | OK |
| origination-desk | terminal-claude | OK | OK | OK | OK |
| ao-desk | terminal-claude | OK | OK | OK | OK |
| movie-desk | terminal-claude | OK | OK | OK | OK |
| baden-baden-desk | terminal-claude | OK | OK | OK | OK |
| brisen-desk | terminal-claude | OK | OK | OK | OK |
| cortex | service | OK | OK | OK | N-A(service) |
| cowork-ah1 | app-claude | OK | OK | OK | N-A(app-resident) |
| cowork-bb-desk | app-claude | OK | OK | OK | N-A(app-resident) |
| cowork-ao-desk | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-movie-desk | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-hag-desk | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-origination-desk | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-researcher | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-arm | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-russo-ai | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-librarian | app-claude | OK | OK | OK | N-A(wakeable:false) |
| cowork-aid | app-claude | OK | OK | OK | N-A(app-resident) |
| CM-1..CM-4 | terminal-claude | OK | OK | OK | OK |
| hag-filer | terminal-claude | OK | OK | OK | OK |
| b5 | terminal-claude | N-A(bus_enabled:false, reserved) | N-A | N-A | N-A |
| bb-finance | vault-seeded | N-A(bus_enabled:false → 400 unknown_recipient_slug) | N-A | N-A | N-A |

`⚠tel` = capability OK at the daemon, but per-seat telemetry stale ~6d (F3) → fleet view shows the live seat as dead. `read` OK means the **list** surface returns rows — subject to the §0 body-blindness caveat (preview-only). `✓` = proven live this session.

### 1b. MUST-do duty profile (role-class, evidence-cited)

| class | seats | exec-on-dispatch | ack-on-read | ship-routing | escalate-to-lead | posture | source |
|---|---|---|---|---|---|---|---|
| build-worker | b1–b4 | **MUST** (HARD 2026-05-27) | **MUST** (HARD 2026-06-11) | **MUST** reply-to-dispatcher (2026-05-17) | MUST (blockers→AH1) | terminal-wakeable | b1:40,127,138 |
| ai-head-terminal | lead, deputy | no (orchestrate/delegate) | no | to Director / reply-to-sender | MUST→Director on Tier-B bounds | terminal-wakeable | aihead1:23,67-101 |
| specialist-terminal | researcher, librarian, arm, russo-ai, clerk-haiku, deep55, aid, codex | **MUST** (dispatch=go) | MUST (housekeeping) | reply-to-sender / flag-to-lead | MUST (blockers→dispatcher) | terminal-wakeable | researcher:58, librarian:44, arm:42 |
| specialist-app | codex-arch, ben, cowork-aid | no (drain-on-open) | MUST when drained | to dispatcher | MUST | app-resident (N/A wake) | cowork-aid:39 |
| matter-desk-terminal | hag-desk, ao-desk, movie-desk, baden-baden-desk, origination-desk, brisen-desk, hag-filer | **UNKNOWN** (D1) | UNKNOWN (D1) | UNKNOWN (D1) | desks→Director (bank model) | terminal-wakeable | **no orientation.md (D1)** |
| matter-desk-cowork | cowork-*-desk | no (drain-on-open) | MUST (cowork-bb-desk:56) | relay→terminal twin / lead | MUST (relay→lead) | app-resident (N/A wake) | cowork-bb-desk:32-56 |
| ai-head-app | cowork-ah1 | no | no | to Director | to Director | app-resident (N/A wake) | aihead1 twin |
| system | cortex, clerk | no (post-only/service) | no | n/a | n/a | N/A wake (service/headless) | registry scope=system |

### 1c. CAN×MUST mismatches (findings)

- **researcher — MUST ack-on-read but CANNOT ack** (ack script rejects its own role). Broken duty → **F2 (P0)**.
- **matter-desk-terminal — duties UNKNOWN**: no `orientation.md` for hag-desk/ao-desk/movie-desk/origination-desk/brisen-desk (only cowork twins documented). These are terminal-wakeable and bus-active (baden-baden-desk has 712 acked msgs) yet their MUST-do profile is uncodified → **D1 (P1)**: a dispatched terminal desk has no written execute-on-dispatch / ack / routing duty; codex-idle-class risk is unmapped for the busiest desks.
- **ack-on-read is a HARD RULE only for b1–b4 + cowork-bb-desk**; specialists ack "implicitly," AH-heads/desks have no rule → **D2 (P2)**: uneven ack discipline is why lead/Director see false-pending counts from seats that handled-but-didn't-ack.
- **reply-to-sender is explicit only for b1–b4 + AH2 + cowork-bb-desk**; specialist workers lack the "read dispatcher from metadata" rule → **D3 (P2)**: mis-routing risk (the 2026-05-30 incident class) is unguarded for researcher/librarian/arm.
- **Over-capability (benign):** all app-resident seats retain post/ack CAN with no wake duty — correctly N/A, not a defect (per #9180-item-2). No surfaces found that a role is forbidden yet exposes on the bus.

---

## §2 Wake-path map

**Class (source `WAKEABLE_TERMINALS` `agent_identity_generated.py:18` + registry `wakeable` flags):**
- **Terminal-wakeable:** lead, deputy, deputy-codex, aid, b1–b4, researcher, codex, clerk-haiku, russo-ai, deep55, librarian, arm, all 6 terminal desks, hag-filer, CM-1..4.
- **App-resident (never autowake; nudge/drain-on-open):** cowork-ah1, ben, codex-arch, cowork-aid, all 5 cowork desks, cowork-researcher/arm/russo-ai/librarian. **BB-Desk incident class (#9147):** an escalation-critical desk that only exists app-resident cannot be woken → misses time-critical mail. **F4 (P1).**
- **Service/headless (no session):** cortex, clerk.

**Topic gate REMOVED** (`bus.py:168-176`, REMOVE_WAKE_TOPIC_GATE_1, Director 2026-06-18): `_is_wake_worthy` = True unconditionally. Only pure-noise suppressed: `kind=ack`, topic-prefix `heartbeat` (`bus.py:237-246`). **No substantive dispatch is topic-suppressed** — a seat idling on a dispatch is an orientation gap (execute-on-dispatch duty), not a gate. Per §1b that duty is present for workers/specialists, **absent/unknown for terminal matter-desks (D1)** and codex (patched 2026-07-11, lessons #118).

**Containment (mechanical, `bus.py:603-690`):** 5s debounce, 120/hr cap, ping-pong auto-disable, env disabled-list, master killswitch. None content-gate.

**wake_events health — UNVERIFIED / no surface (F6, P1):** `/api/wake_events`, `/api/wake/events`, `/api/v2/wake_events`, `/wake_events` all 404. There is **no fleet-visible wake-events read** — wake failures are invisible until a seat misses live work. The daemon writes `wake_attempted_at` per message (visible in the list projection) but there is no aggregate.

---

## §3 Identity layer (MCP shared-key → daemon)

**Two identity models; the defect is entirely MCP-side:**

1. **brisen-lab direct (real fleet transport) — HEALTHY.** `auth_lab.resolve_terminal_key` (`auth_lab.py:75-89`) constant-time-matches `X-Terminal-Key` to a **distinct per-slug** key; mismatch → 401; **no shared key, no `daemon` fallback.** Every picker script (`bus_post.sh`, `ack_dispatch_msgs.sh`) uses its own seat key → correct sender attribution.
2. **Baker MCP tools (`baker_inbox_*`, served by baker-master, NOT brisen-lab) — BROKEN per-seat.** MCP holds one terminal key; the daemon derives the sender from it server-side. `baker_inbox_read(terminal=b1)` → **`403 reader_slug_mismatch`** (proven). `baker_inbox_ack` same. `baker_inbox_post` is worse — it would post under the MCP's bound identity, **silently mis-attributing the sender**.

**Feasibility of per-seat MCP key binding (design only):** technically feasible (MCP reads `BAKER_ROLE`, selects `BRISEN_LAB_TERMINAL_KEY_<role>` at call time) but requires giving the MCP the whole fleet's key blast-radius. **REJECTED** — see §5 disposition. The working per-seat surface already exists: own-key `curl` via the picker scripts.

---

## §4 Broadcast / ack hygiene — ONE policy finding (F5)

Per #9180-item-3, the 251-wildcard backlog is **one missing-policy finding, not 251 rows:**

- **Wildcard `to=['*']` broadcasts are unackable by design.** `POST /msg/{id}/ack` (`bus.py:1289-1296`) requires `ctx.slug in recipients`; `['*']` never contains a real slug → `403`. So `lifecycle/forced-kill|restart|refresh-cadence-sweep` accumulate as permanent `acked=false`.
- **Two read views diverge (`bus.py:1128-1131`):** `unread=true` filters **named-only** (wildcards drop out → true pending count excludes lifecycle noise); `unread=false` (history) returns named OR wildcard, all `acked=false`. Any UI counting `acked=false` in history mode over-reports by the full wildcard backlog. My b1 window: **56–57 wildcard `acked=false` vs 0 real pending.** This is the origin of the brief's "251/251 unacked" symptom — inflated history-mode noise, **not** genuine unhandled mail.
- **`/msg/all` is not a route** — returns 0 even with the real director key (`all` parsed as a slug). Anything assuming a `/msg/all` fleet read (e.g. `/bus-console`) gets an empty set.
- **TTL covers wildcards** (`app.py:367-387`): daily sweep soft-deletes unacked dispatch+broadcast >30d, excluding `ratify_required` + director-mail. The "51 older than 48h" are inside TTL — noise awaiting sweep, not a TTL bug.

**Missing policy (the finding):** there is no rule for *who acks broadcasts* (nobody can) and no short-TTL/auto-expire for `lifecycle/*`, so every fleet-view that counts history-mode `acked=false` is permanently wrong. Fix = policy decision (below), not per-seat work.

---

## §5 Registry / state drift

- **Live cards (41) vs registry: aligned.** `bb-finance` + `b5` (both `bus_enabled:false`) correctly absent from cards/`VALID_BUS_SLUGS`.
- **Hardcoded slug lists centralized** in `agent_identity_generated.py` (generated from registry): `APP_TERMINALS/CARD_SLUGS`(41), `WAKEABLE_TERMINALS`(29), `REFRESHABLE_SLUGS`(26), `PROTECTED_SLUGS`(18), `VALID_BUS_SLUGS`(45), `RECIPIENT_CANONICAL`. Correct anti-drift pattern — the HAGENAUER_DESK "3 lists missed" trap is structurally prevented for these.
- **Hand-maintained residuals in `app.py`:** `CADENCE_SLUGS`(80), `DESK_CADENCE_SLUGS`(100), `DESK_BACKLOG_WAKE_SLUGS`(1367). The last **duplicates** `DESK_CADENCE_SLUGS + hag-filer` (AG-405, parked 2026-07-10) → **F8 (P2)**.
- **Stale mailbox-flag pattern (per #9177):** `CODE_1_PENDING.md` showed `AGENT_WORK_QUEUE_V1: PENDING` for 2 days after the arc closed 2026-07-10 (@4e73aa6a); the flag was never flipped at close-out. Detected only because b1 cross-checked the newer dispatch against the mailbox and flagged (#9176) rather than guessing. **D4 (P2):** mailbox status flags are not reconciled against arc-close; a seat that trusts the flag would work the wrong (closed) brief. Fix = close-out step flips the mailbox flag, or a drift-check hook compares mailbox `status` vs the arc's checkpoint state.
- **Terminal matter-desk orientation absence (D1, §1c)** is also registry/state drift: the desks exist in the registry + cards but have no duty spec on disk.

---

## §6 Prioritized impediment list

P0 = blocks production work · P1 = forces manual Director/lead intervention · P2 = hygiene.

| ID | Sev | Finding | Proposed fix (one line) | Owner |
|---|---|---|---|---|
| **F2** | **P0** | researcher ack script rejects own role → can't ack own inbox (1 msg stuck ~23h); broken MUST-do | Add `researcher` to the ack-script `BAKER_ROLE` case map (same class as bus_post role map) | deputy (assigned) / b-code |
| **F0** | **P1** | Read surface is body-blind: `/msg/{slug}` returns `body_preview` (misnamed, ≤8KB, truncates silently); no `GET /msg/{id}` full-body route → readers keyed on `body` see nothing (near-miss of scope addition #9180 this session) | Alias `body`→full body in the projection + add a full-body single-message route; document the field name | b-code build |
| **F1** | **P1** | Baker MCP bus tools 403 `reader_slug_mismatch` per-seat; `baker_inbox_post` mis-attributes sender | Deprecate MCP bus tools for per-seat use; own-key `curl` scripts are the sole sanctioned surface (don't hand MCP the fleet keys) | lead (doc) |
| **F3** | **P1** | Coder pool + deputy (b1–b4, deputy, deputy-codex) telemetry stale ~6d → fleet view shows live seats dead | Repair the forge snapshot pusher for the terminal-claude coder pool (per `forge-snapshot-push-install`, must run from Terminal) | lead / operator |
| **F4** | **P1** | App-resident escalation-critical desks cannot autowake (BB-Desk #9147); 2 cowork seats hold ~24h-stuck directed mail | Out-of-band nudge path (SMS/push) OR migrate escalation-critical desks to a terminal-wakeable seat | lead / AID design |
| **F6** | **P1** | No fleet-visible `wake_events` surface (all 404) → wake failures invisible | Add `GET /api/v2/wake_events?days=N`; feed `/bus-console` | b-code build |
| **D1** | **P1** | Terminal matter-desks (6 busiest desks) have NO orientation.md → execute-on-dispatch/ack/routing duties uncodified (codex-idle-class risk unmapped) | Author terminal-desk orientation.md (duty profile) for hag/ao/movie/baden-baden/origination/brisen desks | lead / desks |
| **F5** | **P2** | Wildcard `to=*` backlog: unackable-by-design + history-mode `acked=false` count inflates "unacked" (the 251/251 symptom); `/msg/all` not a route | ONE policy: exclude wildcards from any "unacked" UI count (use `unread=true`), + short `lifecycle/*` TTL; add a real fleet-read route | lead decision + b-code |
| **D2** | **P2** | ack-on-read HARD only for b1–b4 + cowork-bb-desk → false-pending from other seats | Promote ack-on-read to a universal duty line in `_universal` orientation | lead |
| **D3** | **P2** | reply-to-sender explicit only for b1–b4/AH2/cowork-bb-desk → mis-route risk for specialists | Add reply-to-sender rule to specialist orientations | lead |
| **D4** | **P2** | Stale mailbox-flag: `CODE_1_PENDING` stayed PENDING 2d after arc close (#9177) | Close-out flips mailbox flag; or drift-check hook mailbox-status vs checkpoint | lead / b-code |
| **F8** | **P2** | `DESK_BACKLOG_WAKE_SLUGS` hand-duplicates `DESK_CADENCE_SLUGS + hag-filer` (AG-405 parked) | Fold into generated `agent_identity_generated.py` | b-code build |
| **F9** | **P2** | Per-seat execute-on-dispatch verified by CLASS (§1b), not per-file for every seat | Confirmed for workers/specialists; gap is D1 (terminal desks) — no separate action | — |

**Counts: P0 = 1 · P1 = 6 · P2 = 5.** (rev1 was P0=1/P1=4/P2=4; rev2 adds F0, D1 at P1 and D2/D3/D4 at P2 from the scope addition + the live body-read catch.)

**MCP per-seat identity fix — explicit disposition (brief item 6):** **REJECTED as a build.** The audit shows the working fix already exists — own-key `curl` via the picker scripts attributes senders correctly. Per-seat key injection into the MCP would hand it the whole fleet's secret blast-radius for zero gain over the working path. Recommend F1 (deprecate/doc the MCP bus tools) instead.

---

## Verification (against brief AC)

1. ✅ Matrix covers 100% of 41 slugs; duty matrix by role-class per #9180; N/A rows carry reasons.
2. ✅ Every BROKEN cell has reproducible evidence (F0 = live near-miss + field dump; F1 = live 403; F2 = ack-script role-map + stuck-msg telemetry; F3 = telemetry_age ~521,790s while seat live).
3. ⚠ Wake map reconciles with `WAKEABLE_TERMINALS` source + registry flags + live telemetry, **not** with `wake_events` (no surface — that gap IS finding F6).
4. ✅ Findings cross-reference every known incident: ARM body-read (F0, live-reproduced despite claimed fix), researcher ack (F2), codex idle (§2 + D1), MCP→daemon (F1), BB-Desk escalation (F4). **The method caught its own body-read defect live** — the AC4 self-check ("would the method have caught the known incident?") passed by accident of hitting it.

## Coverage gaps (no silent truncation, per AC4)

- **wake_events health** — no HTTP surface (404); would need daemon DB access. Recorded as F6.
- **Terminal matter-desk duties** — no orientation.md on disk (D1); duty profile genuinely uncodified, not merely unread.
- **Per-seat live read/ack/post** proven only for b1 (own key); other terminal-seat OK cells inferred from the identical `resolve_terminal_key` mechanism, not individually key-tested (per-seat key sweep skipped — cost/blast-radius).
- **"251/251 unacked" exact origin endpoint** unconfirmed (`/msg/all` returns 0); strong inference (§4) = history-mode `acked=false` wildcard count.
