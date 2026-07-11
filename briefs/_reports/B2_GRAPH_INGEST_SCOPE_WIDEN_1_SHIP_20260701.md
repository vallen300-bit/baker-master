# B2 SHIP REPORT — GRAPH_INGEST_SCOPE_WIDEN_1

- **Brief:** `briefs/_tasks/GRAPH_INGEST_SCOPE_WIDEN_1.md`
- **Dispatched by:** lead (bus #4901); decision Option B (bus #4909)
- **Branch:** `b2/graph-ingest-scope-widen-1`
- **Commit:** `12f9124f`
- **PR:** #450 → base `main`
- **Date:** 2026-07-01
- **Gate handoff:** G1 done (this) → **codex G3 effort HIGH** → **lead G4 `/security-review`** → lead merge → lead live-confirm.

## What shipped
Widened the Graph mail poller from **Inbox-only** to the **whole mailbox** via per-folder delta, minus the never-ingest folders. Surgical to `triggers/graph_mail_trigger.py` (+ its tests) — no other poller touched, no dashboard, no migration, no new env, no deploy from me.

## Design (Option B, lead-decided)
Verified against MS Learn `message: delta`: **Graph has no mailbox-wide message delta** (`/users/{u}/messages/delta` does not exist; delta is per-folder only). So:

1. **Folder enumeration** — `_enumerate_folders`: iterative hierarchy walk incl. nested `childFolders`, bounded by `_FOLDER_WALK_GUARD`. `_get_pollable_folders` caches the list for `_FOLDER_CACHE_TTL` (1h) and refreshes lazily — the poll runs every few minutes, so re-walking each tick would be needless Graph load (lead's guidance). A transient empty re-walk keeps the last known-good cache rather than going blind.
2. **Exclusion (HARD)** — `_excluded_folder_ids` resolves `sentitems/drafts/deleteditems/junkemail` to real ids by **well-known name** (locale-proof); enumeration also drops any folder whose `displayName` is in a deny-set (belt-and-suspenders if well-known resolution hiccups) and **prunes the excluded folder's subtree**.
3. **Per-folder delta + per-folder cursor** — `_poll_folder`: cursor key `graph_mail_poll:folder:<id>` (the process-wide watermark stays on `graph_mail_poll`). The stale legacy `graph_mail_poll` cursor_data row is simply unused now (no migration needed).
4. **Seed-from-now (delta-reset safety)** — first encounter of a folder seeds the initial delta with `$filter=receivedDateTime ge {now − _SEED_LOOKBACK(1d)}` — the **only** filter `message:delta` supports (verified). Graph bakes the bound into the returned deltaLink, so cutover pulls only recent mail, **not** the ~119k history.
5. **Fault-tolerance** — one folder's fetch error is counted (`folder_poll_failures()` surfaced) + logged, and does **not** abort the poll. That folder's cursor is not advanced (retries next tick). Two modes still **raise** (so `check_new_graph_messages` reports failure and does not advance the watermark — no silent success): (a) enumeration yields no folders while ready, (b) **every** folder failed.

## Acceptance criteria — all covered by tests
| AC | Test |
|----|------|
| AC1 non-Inbox subfolder message ingested | `test_non_inbox_folder_message_ingested` |
| AC2 Sent/Drafts/Deleted/Junk not ingested + subtree pruned | `test_excluded_wellknown_and_subtree_pruned`, `test_excluded_folder_ids_resolves_wellknown` |
| AC3 cutover seeded, no full-history backfill | `test_first_encounter_seeds_receiveddatetime_filter`, `test_seed_filter_format` |
| AC4 dedup holds (quiet folder re-emits nothing) | `test_cursored_quiet_folder_reemits_nothing` (+ store `ON CONFLICT` unchanged) |
| AC5 one folder's error does not abort poll | `test_one_folder_failure_does_not_abort_poll` |

Plus: enumeration/nesting, cache hit + TTL refresh, per-folder cursor keying, failure-raises-not-silent-success, mid-pagination raise, @removed/draft skip.

## G1 self-check (literal runs)
- `py_compile` — OK (both files).
- `pytest tests/test_graph_mail_trigger.py` — **34 passed**.
- Sibling: `pytest tests/test_graph_client.py tests/test_backfill_graph.py` — **63 passed**.
- Singleton guard `scripts/check_singletons.sh` — OK.
- **No new raw SQL writes** in the diff (grep INSERT/UPDATE/DELETE/DROP/ALTER → only prose matches). All state writes go through `trigger_state.set_cursor/set_watermark` — the same write surface as before, just per-folder cursor rows. Attachment-capture path unchanged.
- Pre-existing unrelated local failures: `test_m365_large_attachment_fetch` / `test_forward_attachment_parity` error with `ModuleNotFoundError: mcp` (local env lacks the `mcp` package; CI provisions it). Neither file references any changed logic (grep = 0).

## Notes for reviewers (codex G3 HIGH focus areas)
- Delta cutover risk: confirm the seed `$filter` genuinely prevents backfill and that `_SEED_LOOKBACK=1d` is acceptable (bounded, gives a small margin for pre-cutover mail).
- Exclusion completeness: well-known-id resolution failure degrades to displayName deny-set (English). If a well-known folder fails to resolve AND has a localized name, that folder could be polled — logged as WARNING (surfaced). Flagging for the reviewer's judgment.
- Folder-cache is per-process in-memory; a process restart re-enumerates (safe; seeds are idempotent via delta + `ON CONFLICT`).

## Out of scope (untouched)
Reprocessing already-missed historical mail (separate backfill), routing/desk-delivery (`THREAD_CONTINUITY_ROUTING_1`), other mailboxes (office.vienna, bluewin).

---

## F1 fold — codex G3 HIGH: fail-closed hard-exclude (commit `4abb436e`)

**Finding (codex G3, HIGH, worktree-probed on the target mailbox):** the hard-exclude FAILED OPEN. When the well-known folder-id lookup returned None, the fallback was an English-only `displayName` deny-set. Dimitry's mailbox is **German-locale** — codex's probe showed well-known lookups returning None and the top-level Sent folder named **`Gesendete Elemente`**, so `_get_pollable_folders` returned Sent as pollable → own outbound would ingest as inbound and corrupt Box 5 direction logic. (This is the exact fail-open I flagged in the reviewer notes above — codex confirmed it's live and HIGH.)

**Fix:**
1. `_excluded_folder_ids` now returns `(ids, complete)`; `complete=False` iff any well-known folder failed to resolve.
2. `_get_pollable_folders` is **fail-closed**: complete → cache as last-known-good + use it; incomplete but a last-known-good set exists → reuse it (transient blip, no stall); incomplete **and** cold cache → **refuse to poll** (return `[]` → poll raises → `report_failure` → retry). Display-strings are never the sole guard, so an unclassified Sent/Junk under a localized name is never polled.
3. Localized `displayName` deny-set now covers **DE** (`Gesendete Elemente / Entwürfe / Gelöschte Elemente / Junk-E-Mail`) as well as EN — defense-in-depth only.

Option B structure, seed-from-now, and per-folder fault-tolerance unchanged.

**Tests:** `tests/test_graph_mail_trigger.py` — **39 passed** (+5 regression): fail-closed-on-cold-cache (walk never runs), end-to-end poll raises fail-closed (no delta GET issued), last-known-good reuse on a blip, German Sent/Drafts excluded by the localized belt, `_excluded_folder_ids` marks incomplete on a None lookup. Sibling graph tests **63 passed**. Singletons OK.

**Re-gate:** codex G3 (HIGH) again → lead G4 `/security-review` → merge → live confirm.
