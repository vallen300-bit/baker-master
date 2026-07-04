# BRISEN_LAB_BUS_WIRING_FIX_1

**Repo:** `brisen-lab` (base `main`) · **Worker:** b2 · **Dispatcher:** lead (AH1)
**Recommended effort:** high (touches the bus post path + a migration; correctness-critical)
**Origin:** `BRISEN_LAB_BUS_WIRING_AUDIT_1` (cowork read-only audit, 2026-07-04). Audit found 21 ghost recipient slugs stranding ~35 messages, unregistered system slugs, and no post-time recipient validation.

---

## Problem

The bus daemon accepts ANY string in `to_terminals` at post time. Result:
- 51 distinct recipient slugs seen in traffic vs 30 canonical → **21 ghost aliases** (`bb`, `bb-desk`, `baden-baden`, `movie`, `ao`, `origination`, `cowork`, `aihead1`, `aihead2`, `matter-*`, `brisen`, `brisen-desk`, `ticketing-desk`, …). Mail addressed to a ghost slug is never drained by any reader → **~35 stranded messages**.
- `daemon` and `dispatcher` post but have **no `brisen_lab_worker_authority` row** (they ARE in `VALID_BUS_SLUGS` / `SYSTEM_RECIPIENT_SLUGS` but not seeded into the authority table).
- Backlogs never expire: architect 14 unacked (since 11 May), daemon 20 cortex dispatches (since 18 May), director 5, broadcast `*` 20 — no drain owner, no TTL.

The canonical allow-list + alias data **already exist** in `agent_identity_generated.py`:
`VALID_BUS_SLUGS` (30), `SYSTEM_RECIPIENT_SLUGS = ('director','daemon','dispatcher')`, per-agent `aliases` tuples, `WORKER_AUTHORITY_SEED`. This brief wires them into the post path + adds a TTL sweep. It does NOT invent new identity machinery.

**Out of scope (do NOT touch):** key-table / auth model. The audit flagged that session keys died 9 May and identity now rests on a client-supplied slug header (self-printed badge). Director-ratified decision: **defer** — internal private daemon, low threat. Leave a one-line code comment noting "identity = slug header only; keys decorative" at the authz resolution site; no behavioral change.

---

## Tasks

### T1 — Post-time recipient validation + alias canonicalization (`bus.py`, `_post_msg_inner`, ~line 503)
After the `to_terminals` type-check (currently line 504-505), before `_insert`:
1. Build a canonicalizer from `agent_identity_generated`: map every `slug` and every `alias` → canonical `slug`; include `SYSTEM_RECIPIENT_SLUGS` as valid self-canonical.
2. For each recipient in `to_terminals`: resolve alias → canonical slug. If unknown (not a slug, not an alias), reject the whole POST with `HTTPException(400, detail="unknown_recipient_slug:<slug>")`.
3. Insert the **canonicalized** `to_terminals` (so `movie` is stored as `movie-desk`, drainable).
4. Extend the alias data at the registry source so these audit-surfaced ghosts canonicalize (add as `aliases` in `~/baker-vault/_ops/registries/agent_registry.yml`, then regenerate `agent_identity_generated.py` via its generator — do NOT hand-edit the generated file):
   - `baden-baden-desk` += `bb`, `bb-desk`, `baden-baden`
   - `movie-desk` += `movie`
   - `ao-desk` += `ao`
   - `origination-desk` += `origination`
   - `cowork-ah1` += `cowork`
   - `lead` already has `aihead1`; `deputy` already has `aihead2` — verify, no dup.
   - `brisen` / `brisen-desk` → `brisen-desk` exists (seeded, bus_enabled False). Decide: canonicalize to `brisen-desk` and allow, OR reject. Recommend **reject** (it's not bus-active) so senders learn — surface in T-report.
   - `ticketing-desk`, `matter-*`: NOT real agents → reject (400). Surface count in report.

### T2 — Seed missing system-slug authority rows (migration)
`daemon` and `dispatcher` are valid recipients but lack authority rows. Add a migration seeding both at authority level 0 (system, never-ratifies), mirroring the `cortex`/`aid` level-0 rows in `WORKER_AUTHORITY_SEED`. Idempotent (`ON CONFLICT DO NOTHING`).

### T3 — TTL expiry sweep for stale unacked messages
No per-seat drain loops (audit's cheaper-alternative, Director-preferred). Add a periodic sweep (hook into the existing scheduled fleet-refresh cadence loop from commit `df727bf`, or a sibling scheduled task):
- Soft-delete (or mark `expired_at`) unacked `dispatch` + `broadcast` messages older than `BRISEN_LAB_MSG_TTL_DAYS` (env, default **30**).
- Never expire `ratify_required` or Director-addressed messages (safety).
- Log a one-line summary per sweep (count expired). Emit an otel span if the pattern exists.

### T4 — One-time cleanup of the 35 stranded messages (data)
Run against the bus DB (read-then-write, reversible where possible):
- Re-address (or re-post to canonical + soft-delete original) the stranded ghost-slug messages per the T1 canonicalization map.
- For genuinely-dead targets (`matter-*`, `ticketing-desk`, `brisen`): soft-delete with a logged reason; do NOT hard-delete.
- Produce a before/after count in the completion report.

---

## Constraints
- **Additive + reversible.** No hard deletes. Soft-delete only. Migration idempotent.
- Reuse `agent_identity_generated.py` constants — do NOT duplicate the slug list inline.
- Do NOT hand-edit `agent_identity_generated.py` — edit the registry YAML source + regenerate.
- All DB calls in try/except (repo hard rule).
- No change to the auth/key model (out of scope above).
- Tests first where practical: a test that POSTing to a ghost slug → 400, and POSTing an alias → stored canonical.

## Acceptance criteria
1. POST `/msg/<terminal>` with a `to` containing a non-canonical, non-alias slug → **400 `unknown_recipient_slug:*`**; nothing inserted.
2. POST with a known alias (e.g. `movie`, `bb`) → **201**, row's `to_terminals` stored as canonical (`movie-desk`, `baden-baden-desk`).
3. `daemon` + `dispatcher` have authority rows (level 0) after migration; existing rows untouched.
4. TTL sweep expires a seeded >30-day unacked dispatch in a test; leaves a <30-day and any `ratify_required` untouched.
5. Stranded-message cleanup: post-run, `SELECT count(DISTINCT unnest(to_terminals))` over live (non-deleted) messages ⊆ `VALID_BUS_SLUGS`. Report before/after.
6. Existing bus tests green; new tests for AC1/AC2/AC4 added.
7. Live post-deploy AC verdict on the bus per `post-deploy-ac-bus-gate` before DONE.

## Notes for worker
- Post-path handler: `bus.py:473 post_msg` → `_post_msg_inner` (~493). Insert validation after the `to_terminals` list-type guard (~505), before `_insert` (~543).
- Canonical data source: `agent_identity_generated.py` (`VALID_BUS_SLUGS`, `SYSTEM_RECIPIENT_SLUGS`, per-agent `aliases`, `WORKER_AUTHORITY_SEED`), generated from `~/baker-vault/_ops/registries/agent_registry.yml`.
- Cowork-seat identity (reads as `daemon` not `cowork-ah1`) is a **picker-config** problem, NOT this repo — AH1 handles it separately (Baker MCP shared-key maps to daemon; fix = read bus via the brisen-lab helper, not `baker_inbox_read`). Do not attempt from brisen-lab.
