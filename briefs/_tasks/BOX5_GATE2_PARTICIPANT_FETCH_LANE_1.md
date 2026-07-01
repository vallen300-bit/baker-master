# BRIEF — BOX5_GATE2_PARTICIPANT_FETCH_LANE_1

**Assigned:** b4 · **Working dir:** `~/bm-b4` · **dispatched_by:** lead (AH1)
**Task class:** feature (fault-tolerant read/fetch lane; no migration, no deploy) · **Tier:** B
**Harness-V2:** full (Context Contract + done rubric + gate plan below)

---

## Problem (Gate-2 miss — the last inch of the signal journey)

`orchestrator/airport_ticketing_bridge.py::fetch_email_arrivals` (L866-934) decides
**fetch eligibility** solely on a keyword-ILIKE prefilter (`_keyword_ilike_where`,
active keywords = `aukera, annaberg, lilienmatt`). A matter email from a **known
project participant** that does NOT name the project on a **brand-new (unbound)
thread** is never fetched → never routed → the desk never sees it. It only lands in
`box5_dropped_signals` as a `keyword_prefilter` miss (observability lane
`_log_keyword_prefilter_misses`, L783), never as a ticket.

Participant-bound *routing* already exists (`resolve_by_participant` → `_HARD_LANE_REASON_PREFIX`,
L1887) but runs **downstream of fetch** — it only sees arrivals that already passed the
keyword gate. So sender-identity never functions as a *reachability* gate.

## Design (codex-arch ARCH CALL #4974 — "widen Gate-2 in stages")

Add a **SECOND, DECOUPLED fetch lane** keyed on **sender identity in the project
registry**, unioned into the ticketed set. Mirror the exact decoupling discipline the
drop-observability lane already uses (two independent queries, no shared state).

**Contract:**
1. **Keyword MATCH FETCH stays byte-identical** (L887-906). Do NOT touch it. Its parity
   guarantee is load-bearing — the new lane is additive-only.
2. **New participant lane** = a separate bounded query that fetches recent
   `email_messages` whose `sender_email` is a **registered project participant**
   (channel=`email`), **regardless of keyword**. Recommended shape: enumerate the
   registry email-participant set once, then `WHERE sender_email = ANY(%s)` (bounded set
   — today only BB-AUK-001's ~12 email participants, so volume is tiny and safe). If
   `kbl/project_registry_store.py` lacks an "enumerate participants" helper, add one
   (read-only) rather than per-row `resolve_by_participant` calls.
3. **Union by `message_id`** — a message matching BOTH keyword AND participant appears
   **once**. Keyword-lane rows win the merge (they already carry `matched_keywords`);
   participant-only rows carry `matched_keywords=[]`.
4. **Ordering + watermark safety (CRITICAL):** the participant lane MUST use
   `ORDER BY received_date ASC` and respect the same contiguous-prefix watermark
   invariant as the match fetch (L897-901). The unioned arrival list must not let the
   runner advance the watermark past an un-processed participant-lane row. **This is the
   #1 risk — call it out explicitly in your ship report and prove it in a test.**
5. **Route uncertain → safe-default TICKET, never drop pre-classification.** A
   participant-lane arrival flows through the existing routing loop: registered ACTIVE
   code / participant-bound → hard-lane/code-routed TICKET; otherwise the (f) safe-default
   desk-review TICKET. It must NEVER be silently dropped now that it's fetched.
6. **LLM stays out of the reachability gate.** This lane is 100% deterministic registry
   match. No classifier decides fetch eligibility.
7. **Bound + dark-safe:** give the lane its own cap (mirror `_miss_fetch_cap` env pattern)
   and a dark flag (default OFF, e.g. `BOX5_PARTICIPANT_FETCH_LANE_ENABLED`) so merge is a
   no-op until AH1 flips it in Render. Fault-tolerant: any lane failure is caught, the
   shared conn stays usable (rollback per `.claude/rules/python-backend.md`), the tick
   continues, keyword ticketing unaffected.

## Acceptance criteria

- **AC1 (reachability):** a `email_messages` row from a registered participant
  (`sender_email` ∈ BB-AUK-001 participants) with **zero keyword match** on a **new
  thread_id** is fetched by the participant lane and produces a TICKET. Prove with a test
  that FAILS on main (no ticket today) and PASSES after.
- **AC2 (keyword parity):** the keyword match-fetch set is unchanged — existing keyword
  arrivals ticket exactly as before (regression test over the current match query).
- **AC3 (union dedup):** a row matching BOTH keyword AND participant yields exactly ONE
  ticket (dedup_key idempotency holds), with `matched_keywords` preserved from the
  keyword lane.
- **AC4 (watermark safety):** unioning the two lanes does not advance the received_date
  watermark past an un-processed participant-lane arrival. Test the contiguous-prefix
  behavior directly.
- **AC5 (fault tolerance):** participant-lane query failure is caught, conn rolled back,
  keyword ticketing proceeds normally that tick (test the except path).
- **AC6 (dark-safe):** with `BOX5_PARTICIPANT_FETCH_LANE_ENABLED` unset/false, behavior is
  byte-identical to main (lane is a pure no-op). Merge changes nothing until flipped.

## Done rubric

Not "compiles" — **all 6 ACs green in pytest**, AC1 proven fail-on-main, py_compile clean,
`bash scripts/check_singletons.sh` clean, ship report answers each AC by number + names the
watermark-safety proof (AC4).

## Gate plan

G1 (b4 self: pytest all ACs + fail-on-main proof + py_compile + singletons) →
**G3 codex bus** (route to `codex` terminal, effort **high** — reachability-gate change,
watermark interaction, union dedup: real correctness surface) → **G4 AH1 /security-review**
→ AH1 merge → AH1 flips `BOX5_PARTICIPANT_FETCH_LANE_ENABLED=true` in Render (merge-mode) →
live canary (a real BB-AUK-001 participant, keyword-less, new thread → TICKET → baden-baden-desk)
→ POST_DEPLOY_AC_VERDICT to bus.

## Out of scope

- No change to the keyword match fetch. No new migration (read/fetch only; reuse
  `box5_dropped_signals` if you want to mark promoted rows, but not required).
- No LLM classifier. No thread-continuity change (#451 already shipped). No Render flip by
  b4 — AH1 owns env writes.
- Alias-routing stays retired (Director ruling §A-LEAD-0701: explicit code + participant
  identity only; alias matching is unsafe for multi-matter counterparties).

## Anchors

codex-arch ARCH CALL bus #4974 · drop-observability lane pattern PR #452 (af8e58b) ·
conversation-dedup fix PR #453 (2adb861) · project_registry BB-AUK-001 manifest (§A-LEAD-0701) ·
watermark contiguity invariant `fetch_email_arrivals` L897-901.
