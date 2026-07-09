# B2 Ship Report — lifecycle-403-floor (bus/lifecycle-403-floor)

**Date:** 2026-07-09
**Dispatched by:** lead (#7908 diagnostic + #7929 addendum + #7945/#7969 greenlight + #7961 hag-desk case)
**Topic:** `bus/lifecycle-403-floor`
**Repos touched:** baker-master (PR #506, merged) + brisen-lab DB (one-off SQL) + user-global hook install (host + Mac Mini)

---

## Problem

Daemon lifecycle broadcasts are posted with `to_terminals=['*']` (topics `lifecycle/restart`,
`lifecycle/forced-kill`, `lifecycle/refresh-cadence-sweep`). Two independent facts collide:

1. **Read side** — the full-history query `GET /msg/<slug>` (no `unread` flag) OR-expands
   `'*'` to every named slug (`bus.py` L1034), so every agent's drain shows every broadcast.
2. **Ack side** — `POST /msg/<id>/ack` requires *literal* recipiency (`ctx.slug in to_terminals`,
   `bus.py` ~L1191; `authz.require_recipient_of_message`). `'*'` never contains a named slug, so
   the ack returns `403 not_recipient`. No named terminal can ever ack a broadcast.

Result: broadcasts accumulate as a permanent, un-clearable "unread" floor in every agent's drain
(b2 measured 25 since 07:00; baden-baden-desk reported 20→42; BEN 25).

`BUS_WILDCARD_PENDING_FIX` (#7335) already excludes `'*'` from the daemon's `unread=true` branch
**and** filters `acknowledged_at IS NULL` — but the session-start drain hook queried full-history,
so the fix never reached the surface that renders the floor. The dashboard badge
(`/api/v2/terminals`) was already clean — it `unnest`es `to_terminals` and filters
`recipient = ANY(KNOWN_CARD_SLUGS)`; `'*'` is not a card slug. **The leak was drain-only.**

Fallback (b) "wildcard-ack-allow" was rejected: `acknowledged_at` is a single row-level column, so
the first named terminal to ack a `'*'` row would clear the badge for *all* recipients at once +
races. Per-recipient broadcast ack semantics can't ride a shared column.

---

## Fix 1 — drain requests the unread-only view (baker-master PR #506, MERGED)

- **Change:** `tests/fixtures/session-start-bus-drain.sh` — the drain `curl` now passes
  `--data-urlencode "unread=true"`. Reuses the daemon's existing #7335 branch; `'*'` broadcasts
  drop out and only `acknowledged_at IS NULL` rows render. Directed dispatches are unaffected
  (named recipients still render).
- **Test:** `tests/test_bus_drain_hook.py::test_curl_requests_unread_only` (new) asserts the drain
  passes `unread=true`. Literal run pre-merge: **15 passed, 1 failed** — the single failure was
  `test_user_global_matches_repo` (byte-identical drift detector vs the not-yet-installed live
  hook), expected per lead's "install after merge" sequence.
- **Review:** codex G3 (reasoning_effort=medium) **PASS** at d2aeacd3, no findings (#7964) —
  confirmed the query contract, cursor/rendered-ledger no-regression, and comment accuracy.
- **Install (post-merge):** `cp tests/fixtures/session-start-bus-drain.sh` →
  - `~/.claude/hooks/session-start-bus-drain.sh` (this host / MacBook) — drift test **PASS** post-install.
  - `macmini:~/.claude/hooks/session-start-bus-drain.sh` (Mac Mini) — md5 `65b65124c205ba40fd172645a3c405c5`
    byte-identical to local; `unread=true` count = 3.

---

## Fix 2 — one-off soft-delete sweep of stale broadcasts (brisen-lab DB, X=24h)

Guarded one-off SQL (no new endpoint), atomic transaction:

```sql
UPDATE brisen_lab_msg SET deleted_at = NOW()
WHERE '*'=ANY(to_terminals) AND topic LIKE 'lifecycle/%'
  AND deleted_at IS NULL AND created_at < NOW()-INTERVAL '24 hours';
```

| Metric | Value |
|---|---|
| Live `*`-lifecycle before | 45 (20 older-than-24h target, 25 recent kept) |
| Rows swept (soft-deleted) | **20** — ids 4769,4770,5094,5095,5188–5203 |
| Remaining live `*`-lifecycle after | 25 (== recent kept) |
| Directed spot-check (#7960 hag-desk) | still LIVE (`deleted_at IS NULL`) |
| Collateral guard (directed non-`*` soft-deleted last 2 min) | **0** |

Soft-delete is reversible (`deleted_at = NULL`); both read paths filter `deleted_at IS NULL`, so the
swept rows leave every view. The 25 recent (<24h) rows stay in the table for lifecycle history and
are hidden from drains by Fix 1.

---

## Fix 3 — hag-desk / hag-filer ack-authority (VERIFY, #7961)

**Verdict: ack authority is CORRECT for both. No separate authority bug. Their 403s are the same
wildcard-broadcast floor, resolved by Fix 1 + Fix 2.**

Evidence:
1. **Registry** — `hag-desk` (AG-301) and `hag-filer` (AG-405) are both in `VALID_BUS_SLUGS` /
   `BUS_AGENT_SLUGS` / `CARD_SLUGS` / the `AGENTS` registry (`agent_identity_generated.py`). No
   missing entry.
2. **Directed rows are canonical** — all 5 of hag-desk's unacked directed rows have
   `to_terminals = ['hag-desk']` (canonical), **not** the alias `hagenauer-desk`. The "legacy
   alias-row" hypothesis is rejected. hag-filer has **zero** unacked directed rows.
3. **Key resolves to canonical** — `GET /msg/hag-desk` with hag-desk's own terminal key → **HTTP 200**
   (returned row #7960). `RECIPIENT_OF_TERMINAL` requires `slug == terminal`, so the key resolves to
   `hag-desk`. The ack check `'hag-desk' in ['hag-desk']` therefore passes — a directed ack **cannot**
   403. The 403s hag-desk observed were on the `'*'` broadcast rows in its drain (mis-attributed as
   "directed"), which Fix 1 (hides from drain) + Fix 2 (sweeps old ones) resolve.

No code change required for hag-desk/hag-filer. If a future hardening is wanted, canonicalizing both
sides at ack-time (`canonical_recipient(ctx.slug)` vs `[canonical_recipient(r) …]`) would make ack
robust to any legacy alias rows — flagged for lead, not built (no such rows exist today).

---

## POST_DEPLOY_AC_VERDICT v1

```
POST_DEPLOY_AC_VERDICT v1
topic: bus/lifecycle-403-floor
verdict: PASS
checks:
  - fix1_hook_passes_unread_true: PASS (test_curl_requests_unread_only; codex G3 PASS d2aeacd3)
  - fix1_installed_host: PASS (drift test test_user_global_matches_repo green post-install)
  - fix1_installed_mini: PASS (md5 65b65124c205ba40fd172645a3c405c5 byte-identical; unread=true x3)
  - fix1_drain_surface_clean: PASS (GET /msg/b2 unread=true -> star_rows=0; full-history -> 25 kept)
  - fix2_sweep: PASS (20 soft-deleted >24h; 25 recent kept; #7960 directed survived; 0 collateral)
  - fix2_no_old_star_lifecycle_remain: PASS (fleet-wide count older-than-24h = 0)
  - fix3_hag_ack_authority: PASS (registry OK; canonical rows; key->hag-desk GET 200; no separate bug)
evidence: PR #506 (merged), codex #7964, DB one-off SQL (this report), read-only key-resolution GET
```
