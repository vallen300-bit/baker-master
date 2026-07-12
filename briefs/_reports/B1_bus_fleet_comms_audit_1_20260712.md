# B1_bus_fleet_comms_audit_1 — Fleet Bus-Communications Audit (diagnose-only)

**Brief:** `briefs/_tasks/BUS_FLEET_COMMS_AUDIT_1.md` (dispatch #9165, Director-directed 2026-07-12).
**Author:** b1. **Date:** 2026-07-12. **Class:** diagnose-only, READ-ONLY (no fixes; no bus writes beyond self-addressed test posts + acks).
**Harness-V2:** N/A per brief (audit; output is findings + prioritized fix list for lead ratification).

## Method + evidence base

- Live daemon `origin/main` @ `8e81029` (brisen-lab), production at `https://brisen-lab.onrender.com`.
- Live per-seat telemetry: `GET /api/v2/terminals` (director key) — 41 cards, full unacked/telemetry fields.
- Own-seat live surface test (b1): `GET /msg/b1` read OK; `POST /msg/9165/ack` → 200; `bus_post.sh` #9176 → 200. Terminal-seat read/ack/post proven end-to-end on my own key.
- Static route inspection: `app.py` `bus.py` `authz.py` `auth_lab.py` `db.py` `lifecycle.py` `agent_identity_generated.py` at @8e81029 (file:line anchors below).
- MCP identity test: `baker_inbox_read(terminal=b1)` → **HTTP 403 `reader_slug_mismatch`** (reproduced live).
- Registry: `~/baker-vault/_ops/registries/agent_registry.yml`; install SOP 12-row map (`install-agent-to-brisen-lab`).

**Coverage: 100% of the 41 registry/card slugs.** No silent omissions; N/A rows carry reasons. Two items could not be verified against a live source and are flagged UNVERIFIED (wake_events health; the "251 unacked" symptom origin) — see §Coverage gaps.

---

## §1 Seat I/O matrix

Columns: **read** = own-key `GET /msg/{slug}` returns bodies; **ack** = own-key `POST /msg/{id}/ack`; **post** = own-key `bus_post.sh`/`POST /msg`; **wake** = daemon autowake reachable. Cell = OK / BROKEN(evidence) / N-A(reason).

Determination is by **runtime class** (surface capability is set by runtime + picker wiring, not per-slug) plus per-seat exceptions. Terminal-seat OK cells are proven by the b1 end-to-end test; same key mechanism (`auth_lab.resolve_terminal_key`, `authz.py:161`) applies to every seat holding its own `BRISEN_LAB_TERMINAL_KEY_<slug>`.

| slug | runtime | read | ack | post | wake | notes |
|---|---|---|---|---|---|---|
| lead | terminal-claude | OK | OK | OK | OK | telemetry fresh |
| deputy | terminal-claude | OK | OK | OK | OK⚠ | telemetry stale ~6d (F3); 3 unacked, oldest 12m |
| deputy-codex | terminal-codex | OK | OK | OK | OK⚠ | telemetry stale ~6d (F3) |
| aid | terminal-claude | OK | OK | OK | OK | fresh |
| b1 | terminal-claude | **OK✓** | **OK✓** | **OK✓** | OK⚠ | proven live this session; telemetry stale ~6d (F3) |
| b2 | terminal-claude | OK | OK | OK | OK⚠ | telemetry stale ~6d (F3) |
| b3 | terminal-claude | OK | OK | OK | OK⚠ | telemetry stale ~6d (F3) |
| b4 | terminal-claude | OK | OK | OK | OK⚠ | telemetry stale ~6d (F3) |
| researcher | terminal-claude | OK | **BROKEN** | OK | OK | ack picker script rejects own role (F2, brief #9161-3); 1 unacked stuck ~23h |
| codex | terminal-codex | OK | OK | OK | OK | fresh |
| codex-arch | app-codex | OK | OK | OK | N-A | app-resident, cannot autowake |
| clerk | headless-qwen3 | OK | OK | OK | N-A | headless worker, no interactive session to wake |
| clerk-haiku | terminal-claude-haiku | OK | OK | OK | OK | status=planned (card live, 0 acked) |
| russo-ai | terminal-claude | OK | OK | OK | OK | fresh |
| deep55 | terminal-openai-raw | OK | OK | OK | OK | status=planned |
| ben | app-claude | OK | OK | OK | N-A | app-resident, cannot autowake |
| librarian | terminal-claude-sonnet | OK | OK | OK | OK | fresh |
| arm | terminal-claude-sonnet | OK | OK | OK | OK | telemetry None (no recent push) |
| hag-desk | terminal-claude | OK | OK | OK | OK | fresh |
| origination-desk | terminal-claude | OK | OK | OK | OK | fresh |
| ao-desk | terminal-claude | OK | OK | OK | OK | fresh |
| movie-desk | terminal-claude | OK | OK | OK | OK | fresh |
| baden-baden-desk | terminal-claude | OK | OK | OK | OK | fresh |
| brisen-desk | terminal-claude | OK | OK | OK | OK | fresh (BRISEN_DESK_ON_BUS_1) |
| cortex | service | OK | OK | OK | N-A | system service, no session; excluded from WAKEABLE by design |
| cowork-ah1 | app-claude | OK | OK | OK | N-A | app-resident, cannot autowake |
| cowork-bb-desk | app-claude | OK | OK | OK | N-A | app-resident; telemetry stale |
| cowork-ao-desk | app-claude | OK | OK | OK | N-A | `wakeable:false` in registry |
| cowork-movie-desk | app-claude | OK | OK | OK | N-A | `wakeable:false`; 1 unacked stuck ~24h |
| cowork-hag-desk | app-claude | OK | OK | OK | N-A | `wakeable:false` |
| cowork-origination-desk | app-claude | OK | OK | OK | N-A | `wakeable:false` |
| cowork-researcher | app-claude | OK | OK | OK | N-A | `wakeable:false` |
| cowork-arm | app-claude | OK | OK | OK | N-A | `wakeable:false` |
| cowork-russo-ai | app-claude | OK | OK | OK | N-A | `wakeable:false` |
| cowork-librarian | app-claude | OK | OK | OK | N-A | `wakeable:false` |
| cowork-aid | app-claude | OK | OK | OK | N-A | app-resident; in live cards |
| CM-1 | terminal-claude | OK | OK | OK | OK | fresh |
| CM-2 | terminal-claude | OK | OK | OK | OK | fresh |
| CM-3 | terminal-claude | OK | OK | OK | OK | fresh |
| CM-4 | terminal-claude | OK | OK | OK | OK | fresh |
| hag-filer | terminal-claude | OK | OK | OK | OK | fresh |
| b5 | terminal-claude | N-A | N-A | N-A | N-A | status=reserved, `bus_enabled:false` — not in VALID_BUS_SLUGS |
| bb-finance | vault-seeded | N-A | N-A | N-A | N-A | status=seeded, `bus_enabled:false` — POST/GET → 400 `unknown_recipient_slug` |

**Overlay finding (F1, applies to ALL seats): the Baker MCP bus tools (`baker_inbox_read`/`_post`/`_ack`) are BROKEN for per-seat I/O.** They authenticate with the MCP server's single terminal key; the daemon derives the sender server-side from that key. Asking the MCP to act as any other seat → `403 reader_slug_mismatch` (proven: `baker_inbox_read(terminal=b1)`). So a seat that reads/acks via MCP instead of its own picker `curl`+key gets 403. The direct-`curl`+own-key path (the `bus_post.sh`/`ack_dispatch_msgs.sh` scripts) is the ONLY working per-seat surface today.

---

## §2 Wake-path map

**Wakeability class** (source: `WAKEABLE_TERMINALS`, `agent_identity_generated.py:18`; registry `wakeable` flags):
- **Terminal-wakeable (autowake reachable):** lead, deputy, deputy-codex, aid, b1–b4, researcher, codex, clerk-haiku, russo-ai, deep55, librarian, arm, hag-desk, origination-desk, ao-desk, movie-desk, baden-baden-desk, brisen-desk, CM-1/2/3/4, hag-filer.
- **App-resident (never autowake; nudge-only):** cowork-ah1, ben, codex-arch, cowork-bb/ao/movie/hag/origination-desk, cowork-researcher/arm/russo/librarian/aid. Physically cannot be woken by the daemon — they only see a message when a human/operator drives the app session. **This is the BB-Desk incident class (brief #9147):** app-resident desk missed an airport-ticket escalation because nothing can autowake it.
- **Service/headless (no session to wake):** cortex (service), clerk (headless-qwen).

**Topic gate (source: `bus.py:168-176`, `237-246`):** the topic allow-list was **removed** (REMOVE_WAKE_TOPIC_GATE_1, Director 2026-06-18 — "if you receive the bus, you should wake up"). `_is_wake_worthy` now returns True unconditionally. Only two suppressions remain, both pure-noise: `kind=ack` (`suppressed_ack`) and topic prefix `heartbeat` (`suppressed_heartbeat`). So **no substantive dispatch is topic-suppressed** — a seat that idles on a dispatch is an orientation gap, not a gate.

**Containment (mechanical, `bus.py:603-690`):** 5s per-slug debounce, 120 wakes/hr cap, ping-pong auto-disable (3 loop edges/5min → both slugs disabled 1h), env disabled-list, master killswitch. None of these content-gate.

**Codex-class "wakes but treats dispatch as FYI" (brief item 2):** the daemon wakes correctly; the gap is in each seat's **orientation** (execute-on-dispatch rule). b1/b2/b3/b4 carry the DISPATCH=RATIFIED / superior-dispatch rule (verified in b1 orientation). codex was patched 2026-07-11 (lessons #118). **Method note:** I could not enumerate every seat's orientation for an execute-on-dispatch clause without reading 41 picker files — flagged as a P2 follow-up sweep (F7), not completed this session (runtime cap).

**wake_events 7d health — UNVERIFIED.** No `wake_events` HTTP surface exists (`/api/wake_events`, `/api/wake/events`, `/api/v2/wake_events`, `/wake_events` all 404). Wake health can only be read from the daemon DB directly (no seat has that surface) or added as an endpoint. This is itself a finding (F6): **there is no fleet-visible wake-events surface** — wake failures are invisible until a seat misses live work.

---

## §3 Identity layer (MCP shared-key → daemon)

**Confirmed and scoped.** There are **two** bus identity models, and the defect is entirely on the MCP side:

1. **brisen-lab direct (the real fleet transport) — HEALTHY.** `auth_lab.resolve_terminal_key` (`auth_lab.py:75-89`) constant-time-matches the presented `X-Terminal-Key` to a **distinct per-slug** key; mismatch → 401; there is **no** shared key and **no** `daemon` fallback slug. Every picker script (`bus_post.sh`, `ack_dispatch_msgs.sh`) uses its own seat key → correct sender attribution.
2. **Baker MCP tools (`baker_inbox_*`, served by baker-master, NOT brisen-lab) — BROKEN per-seat.** The MCP holds one terminal key; the daemon derives the sender from it server-side (the `terminal=` arg is honored only client-side for the read target). Any per-seat use fails: `baker_inbox_read(terminal=b1)` → `403 reader_slug_mismatch` (proven live). So the MCP can only ever act as the single slug its key maps to.

**Which MCP bus tools are unusable per-seat:** `baker_inbox_read`, `baker_inbox_ack` (both slug-checked → 403 for non-bound seats), and `baker_inbox_post` (would post under the MCP's bound identity, mis-attributing the sender — silent wrong-sender, worse than a 403).

**Per-seat key binding in MCP — feasibility sketch (design only, no build):** feasible. The MCP server currently injects one static `X-Terminal-Key`. Bind per-seat by having the MCP read `BAKER_ROLE` (already the default for `baker_inbox_read.terminal`) and select the matching `BRISEN_LAB_TERMINAL_KEY_<role>` from 1Password/env at call time, instead of a single shared key. Cost: MCP needs read access to all seat keys (secret-blast-radius tradeoff) OR the seat passes its own key through the tool call (cleaner, but changes the tool contract). **Recommendation: REJECT the shared-key-blast-radius variant; the direct-`curl`+own-key path already works and is what every picker uses.** The real fix is smaller — see F1 disposition in §6.

---

## §4 Broadcast / ack hygiene

- **Wildcard `to=['*']` broadcasts are UNACKABLE by any named terminal — by design.** `POST /msg/{id}/ack` (`bus.py:1289-1296`) requires `ctx.slug in recipients`; a wildcard recipient list is `['*']`, which never contains a real slug → `403 forbidden`. So lifecycle broadcasts (`lifecycle/forced-kill`, `/restart`, `/refresh-cadence-sweep`) can **never** be acked and accumulate as permanent `acked=false`.
- **Two read views diverge (`bus.py:1128-1131`):** `unread=true` (pending) filters **named-only** — wildcards **drop out**, so a seat's true pending count excludes lifecycle noise. `unread=false` (history) returns named **OR** wildcard, all with computed `acked=false` (`bus.py:486-488`). **Any consumer that counts `acked=false` in history mode over-reports "unacked" by the full wildcard backlog.** My own b1 window: 57 wildcard `acked=false` vs 0 real pending. This is almost certainly the source of the brief's "251/251 unacked" symptom — a history-mode count of unackable lifecycle broadcasts, not genuine unhandled mail.
- **TTL does cover wildcards (`app.py:367-387`):** the daily sweep soft-deletes unacked `dispatch`+`broadcast` older than 30d (`BRISEN_LAB_MSG_TTL_DAYS`), excluding `ratify_required` and director-addressed mail. So wildcards <30d persist (expected); >30d get swept. The 51-older-than-48h in the symptom are well inside TTL — they are **not** a TTL bug, they are unackable-by-design noise awaiting the 30d sweep.
- **`/msg/all` is not a real route.** `GET /msg/all` (director key, both `unread` modes) returns **0** — the daemon treats `all` as a terminal slug that matches nothing. Anything (e.g. `/bus-console`) that assumes a `/msg/all` fleet-read gets an empty set. Fleet-wide reads must aggregate per-slug or add a real all-terminals route.

---

## §5 Registry drift

- **Live cards (41) vs registry:** aligned. `bb-finance` (seeded, `bus_enabled:false`) and `b5` (reserved, `bus_enabled:false`) are correctly **absent** from live cards / `VALID_BUS_SLUGS`.
- **Hardcoded slug lists are centralized** in `agent_identity_generated.py` (generated from the registry): `APP_TERMINALS`/`CARD_SLUGS` (41), `WAKEABLE_TERMINALS` (29), `REFRESHABLE_SLUGS` (26), `PROTECTED_SLUGS` (18), `VALID_BUS_SLUGS` (45), `RECIPIENT_CANONICAL` (aliases). This is the correct anti-drift pattern (single generated source) — the HAGENAUER_DESK_ON_BUS_1 "3 hardcoded lists missed" trap is structurally prevented for these.
- **Residual hand-maintained lists in `app.py`** not generated: `CADENCE_SLUGS` (b1-b4, deputy-codex, codex — line 80), `DESK_CADENCE_SLUGS` (6 desks — line 100), `DESK_BACKLOG_WAKE_SLUGS` (line 1367). `DESK_BACKLOG_WAKE_SLUGS` **duplicates** `DESK_CADENCE_SLUGS + hag-filer` (AG-405, parked 2026-07-10) — minor drift risk (F8).
- **No orphaned/stranded slugs found.** Alias canonicalization (`RECIPIENT_CANONICAL`, `bus.py:1731-1743`) resolves AH1/aihead1→lead, ao/ao_desk→ao-desk, movie/movie_desk→movie-desk, bb/bb-desk→baden-baden-desk, etc. `director`/`daemon`/`dispatcher` are self-canonical system recipients that bypass the bus-enabled filter (`agent_identity_generated.py:13`).

---

## §6 Prioritized impediment list

Rated P0 (blocks production work) / P1 (forces manual Director/lead intervention) / P2 (hygiene). Each: one-line fix + suggested owner.

| ID | Sev | Finding | Proposed fix (one line) | Owner |
|---|---|---|---|---|
| **F2** | **P0** | researcher `ack` script rejects its own role → cannot ack its own inbox; 1 msg stuck ~23h | Add `researcher` to the ack-script `BAKER_ROLE` case map (same bug class as bus_post role map) | deputy (already assigned per brief) / b-code |
| **F1** | **P1** | Baker MCP bus tools 403 (`reader_slug_mismatch`) for every non-bound seat; `baker_inbox_post` would mis-attribute sender | Deprecate MCP bus tools for per-seat use; document own-key `curl` scripts as the sole sanctioned surface. Do NOT give MCP all seat keys | lead (doc) |
| **F3** | **P1** | Coder pool + deputy (b1-b4, deputy, deputy-codex) telemetry stale ~6d → `/api/v2/terminals` + `/bus-console` show live seats as dead | Install/repair the forge snapshot pusher for the terminal-claude coder pool (per `forge-snapshot-push-install` how-to; must run from Terminal not Cowork) | lead / per-seat operator |
| **F4** | **P1** | app-resident desks cannot autowake (BB-Desk missed escalation #9147); 2 cowork seats hold ~24h-stuck directed mail | No daemon fix possible — needs an out-of-band nudge path (SMS/push) OR migrate escalation-critical desks to a terminal-wakeable seat | lead / AID design |
| **F6** | **P1** | No fleet-visible `wake_events` surface (all 404) → wake failures invisible until a seat misses live work | Add `GET /api/v2/wake_events?days=N` read endpoint; feed `/bus-console` | b-code build |
| **F5** | **P2** | `/msg/all` returns 0 (not a real route); history-mode `acked=false` count includes unackable wildcards → "251 unacked" is inflated noise, not real backlog | Add a real all-terminals aggregate route; make `/bus-console` count pending in `unread=true` mode (excludes wildcards) | b-code build |
| **F7** | **P2** | Per-seat execute-on-dispatch orientation not fleet-verified (codex-class idle gap); only spot-checked b1/codex | One-pass sweep: grep every picker orientation for a DISPATCH=RATIFIED/execute-on-dispatch clause; patch gaps | deputy / b-code |
| **F8** | **P2** | `DESK_BACKLOG_WAKE_SLUGS` hand-duplicates `DESK_CADENCE_SLUGS + hag-filer` (AG-405 parked) | Fold into the generated `agent_identity_generated.py` source | b-code build |
| **F9** | **P2** | Wildcard lifecycle broadcasts unackable-by-design → permanent `acked=false` until 30d TTL | Optional: shorten a `lifecycle/*` TTL to e.g. 72h, or exclude wildcards from any "unacked" UI count | lead decision |

**Counts: P0 = 1 · P1 = 4 · P2 = 4.**

**MCP per-seat identity fix — explicit disposition (brief item 6):** **REJECTED as a build.** The brief framed it as a shared-key→daemon defect to fix; the audit shows the *fix already exists* — the direct own-key `curl` path (every picker's `bus_post.sh`/`ack_dispatch_msgs.sh`) works and attributes senders correctly. The right action is F1 (deprecate/doc the MCP bus tools for per-seat use), not per-seat key injection into the MCP (which would hand the MCP the whole fleet's secret blast radius for no gain over the working path).

---

## Verification (against brief AC)

1. ✅ Matrix covers 100% of the 41 registry/card slugs; N/A rows carry reasons.
2. ✅ Every BROKEN cell has reproducible evidence (F1 = live 403; F2 = ack-script role map + stuck-msg telemetry; F3 = telemetry_age ~521,790s while seat live).
3. ⚠ Wake map reconciles with `WAKEABLE_TERMINALS` source + registry flags + live telemetry, **but not with `wake_events` data** — no such surface exists (that gap is finding F6).
4. ✅ Findings cross-reference every known incident: ARM (identity/read — model validated), researcher ack (F2), codex idle (F7/§2), MCP→daemon (F1), BB-Desk escalation (F4). Method note where a sweep was not run (F7).

## Coverage gaps (no silent truncation, per AC4)

- **F7** per-seat orientation sweep NOT run (would require reading ~30 picker files; runtime cap). Spot-checked b1 (has rule) + codex (patched). Recommended as a P2 follow-up.
- **wake_events health** NOT obtained — no HTTP surface (404); would need daemon DB access. Recorded as finding F6.
- **"251/251 unacked" symptom** — could not reproduce via `/msg/all` (returns 0). Strong inference (§4): it is a history-mode `acked=false` count of unackable wildcards. Exact origin endpoint unconfirmed.
- Live per-seat read/ack/post proven **only** for b1 (own key); all other terminal-seat OK cells are inferred from the identical `resolve_terminal_key` mechanism, not individually key-tested (per-seat keys not swept — cost/blast-radius).
