---
status: COMPLETE
brief: briefs/BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md
trigger_class: TIER_B_AUTH_SURFACE_PLUS_NEW_ENV_VAR
dispatched_at: 2026-05-11
dispatched_by: ai-head-a
claimed_by: b4
brief_revisions: V0.1 + V0.2 fold + V0.3 fold (4-gate + Gate 4 fault-tolerance fold)
pr: https://github.com/vallen300-bit/brisen-lab/pull/9
pr_head_v0_1: 3e2fc3c8213b282cc763d81882eddc19adb61824
pr_head_v0_2: 58d17c4cd3758c83ac0518eabf9496be1d863511
pr_head_v0_3: b2eef4f05e971ae3c9b678ff0a97073fb4b418a3
merged_at: 2026-05-11T11:05:22Z
merge_commit: 96ed2702ef7a2a0ff77410452cfe45eba10eb103
post_merge_deploy: dep-d80rft67r5hc739squeg
env_var_put: RENDER_API_KEY on srv-d7q7kvlckfvc739l2e8g 2026-05-11 ~11:05Z
aid_close_out_msg: 84
---

## COMPLETE — 2026-05-11 ~11:08Z

All ACs A1-A18 GREEN. 6/6 live smoke tests pass:
1. AID list services → 200 (count=4)
2. AID env-vars on baker-master → 200 (count=67, BAKER_VAULT_PATH visible at correct value)
3. lead list services → 200
4. b1 list services → 403 not_authorized_for_render_config
5. no key → 401 bad_terminal_key
6. malformed service-id → 400 invalid_service_id

Gate chain summary across V0.1→V0.3:
- V0.1: 4 gates ran (B4 pytest + AH2 /security-review + AH1 architect + AH1 code-reviewer 2nd-pass)
  - Gate 2 HIGH: audit emission gap → folded as F1 in V0.2
  - Gates 2/3/4 convergent MEDs: service_id regex, httpx-level tests, allow_director dead kwarg → folded as F2/F3/F4 in V0.2
- V0.2: Gates 1 + 4 re-ran (Gate 2 idle past ultimatum; Gate 3 skipped — V0.1 shape unchanged)
  - Gate 4 MED M1: audit_emitter not fault-tolerant → folded as F5 in V0.3
- V0.3: Gates 1 + 4 re-ran (Gate 2 skipped per V0.3 plan)
  - Gate 4 PASS — clean

Deferred (NOT in this brief):
- Depends-layer whitelist via Policy enum (architect MED, structural)
- Split env-vars endpoint into keys-only + per-key-audited (Gate 2 MED#3 design)
- httpx client pooling
- Pagination truncated flag
- print() → structured logger with otel context
- Regex anchor cosmetic cleanup (Gate 4 V0.2 LOW)

Post-merge:
- Bus msg #84 to AID — endpoint live + example queries + service IDs.
- Closes original AID ask (msg #59 thread): Render-MCP gap.


## V0.3 FOLD — 2026-05-11 ~10:35Z (Director-ratified "go" on AH1's recommendation)

V0.2 re-gate chain result:
- Gate 1 (B4 pytest V0.2): GREEN — 25/25 test_render_config.py + 109/1-skipped full suite
- Gate 2 (AH2 /security-review V0.2): NOT RUN — AH2 idle past 5-10 min ultimatum window; AH1 proceeding per AID v1.1 §4. AH2's V0.1 findings already folded in V0.2 + verified by Gate 4 V0.2.
- Gate 4 (feature-dev:code-reviewer V0.2, agent a3eb6c980ee943215): PASS-WITH-NITS — 1 MED + 1 LOW. All 4 V0.2 fold items (F1-F4) VERIFIED landed correctly in code.

### Required fold item (1 only)

**F5 (Gate 4 V0.2 MED M1 — audit_emitter not fault-tolerant).**

`render_config.py` `list_services` (~L153-161) and `get_env_vars` (~L191-200) call `await audit_emitter(...)` AFTER the Render API success path and BEFORE the `return out`. The call has NO try/except. If the bus/DB layer behind `audit_emitter` throws (network blip, queue full, transient psycopg2 error), the handler returns 500 to the caller even though the Render read succeeded and `out` is fully built. Violates CLAUDE.md hard rule: "All DB/API calls wrapped in try/except — fault-tolerant or it doesn't ship."

Fix:
- Wrap each `await audit_emitter(...)` in `try / except Exception as e:`. Log with `print("[render_config] audit emit failed: ...", file=sys.stderr, flush=True)` — same pattern used at `render_config.py` L102 for httpx network errors. Continue after; do NOT raise.
- Audit failure must NOT block the response — the read data is already valid in `out`. Failure to audit is a separate-concern observability gap, not a request-level failure.

Test: 1 new — `test_envvars_read_returns_200_when_audit_emitter_raises`. Mock `audit_emitter` to raise `RuntimeError("bus down")`. Assert handler returns 200 + the env_vars body, AND captures stderr containing "audit emit failed". Mirror for `test_services_read_returns_200_when_audit_emitter_raises` if cheap (single fixture parametrization).

### NOT folded (Gate 4 V0.2 LOW L1, deferred)

- Regex anchor cleanup `re.compile(r"^srv-[A-Za-z0-9_-]+$")` + `fullmatch()`: anchors redundant with fullmatch. Cosmetic. Defer indefinitely — not worth a fold cycle.

### Acceptance criteria (V0.3)

| AC | Source | Verification |
|---|---|---|
| **A16** | F5 audit_emitter try/except wrap | `test_envvars_read_returns_200_when_audit_emitter_raises` + `test_services_read_returns_200_when_audit_emitter_raises` GREEN; stderr contains "audit emit failed" |
| **A17** | Audit emit failures do NOT alter response body | the 200 response body in the failure test = the same body returned in the success test (matches normal-path shape) |
| **A18** | Full suite no regressions | `pytest tests/ -v` GREEN |

### Post-fold re-gate chain (V0.3)

- Gate 1: B4 pytest GREEN (literal)
- Gate 4: AH1 feature-dev:code-reviewer 3rd-pass on V0.3 diff (verify M1 fix + no scope creep)
- Gate 2: SKIPPED — V0.3 is a 3-line fault-tolerance patch on already-AH2-cleared surface (audit emission shape from V0.2 is unchanged; only the failure-handling around the existing call site)

### Sequencing

1. `cd ~/bm-b4-brisen-lab && git fetch origin && git checkout b4/render-config-read-1 && git pull --ff-only`.
2. Edit `render_config.py` — wrap both `await audit_emitter(...)` calls in try/except per F5.
3. Add the 1-2 new tests to `tests/test_render_config.py`.
4. `pytest tests/test_render_config.py -v` GREEN (expect ~26-27 tests post-fold).
5. `pytest tests/ -v` GREEN.
6. Push to `b4/render-config-read-1`. PR #9 auto-updates.
7. Ship report to /msg/lead per AH1 routing.

### Anchors

- Director ratification: 2026-05-11 ~10:35Z "go" on AH1's V0.3 recommendation
- Gate 4 V0.2 verdict: feature-dev:code-reviewer agent `a3eb6c980ee943215`
- AID CONTRACT v1.1 §4 — gate sequencing + fold scope is AH1's

---

## V0.2 FOLD — 2026-05-11 ~09:30Z (Director-ratified "go" on AH1's recommendation)

4-gate consolidation on PR #9:
- Gate 1 (B4 pytest): GREEN
- Gate 2 (AH2 /security-review, msg #72): PASS-WITH-CONCERNS — 1 HIGH + 3 MED + 1 LOW
- Gate 3 (architect, agent addb10afec991e8ac): PASS-WITH-CONCERNS — 3 MED + 3 LOW
- Gate 4 (feature-dev:code-reviewer, agent a771b185e0d5c0e1f): PASS-WITH-NITS — 1 HIGH + 2 MED + 2 LOW

### Required fold items (all 4 must land in V0.2)

**F1 (Gate 2 HIGH — audit emission on env-vars reads).**
`/render/services/{id}/env-vars` returns plaintext production secrets (Anthropic / Voyage / Neon / Render bearer) but emits no `bus_audit` row. Other endpoints on brisen-lab already audit via `bus.make_audit_emitter` (wired at `app.py:94`). Compromise of any one whitelisted terminal key = silent exfil with zero trail.

Fix:
- Pass `audit_emitter` (the `await bus.make_audit_emitter(_broadcast)` return value already created at `app.py:92`) into `render_config.register()` — same signature pattern as `bus.register(app, _broadcast)` but with `audit_emitter` instead of broadcast_fn.
- Inside `get_env_vars` handler (POST-success, BEFORE the `return`): emit an audit row with shape `{kind: "audit", topic: "render-config/env-vars-read", from: ctx.slug, service_id: service_id, env_var_count: len(out), ts: <iso>}`. Use the existing audit_emitter signature — read `bus.make_audit_emitter` source to confirm shape.
- Add audit emission to `list_services` too (lower-stakes, but symmetric — single-pattern across both routes).
- Tests: 2 new — `test_envvars_read_emits_audit` + `test_services_read_emits_audit`. Mock the audit_emitter on the registered route fixture; assert one call with expected shape per request. NO secret values land in the audit row — only counts + service_id + slug.

**F2 (convergent across Gates 2 MED#1 + 3 LOW + 4 MED M1 — service_id regex tighten).**
Current guard at `render_config.py:170` is `startswith("srv-") + len<=64 + no "/"`. Misses `?`, `&`, `#`, `%`, whitespace. `srv-aaa?injected=1` slips through, httpx ends up calling a different Render endpoint with garbled query.

Fix:
- Replace the 3-clause check with `re.fullmatch(r"^srv-[A-Za-z0-9_-]+$", service_id)`. Render service IDs are alphanumeric ULID-ish; this regex covers them and fails-closed on anything else.
- Tests: keep existing `test_envvars_invalid_service_id_*` tests but ADD: `test_envvars_invalid_service_id_with_query_char` (e.g., `srv-aaa?injected=1` → 400), `test_envvars_invalid_service_id_with_hash` (`srv-aaa#frag` → 400), `test_envvars_invalid_service_id_with_percent` (`srv-aaa%20foo` → 400).

**F3 (convergent across Gates 2 MED#2 + 4 MED M2 — httpx-level error mapping tests).**
Current tests at `tests/test_render_config.py:191-211` mock `render_config._render_get` directly. They prove FastAPI passes the pre-built `HTTPException` through; they do NOT exercise the actual `httpx.TimeoutException → 504` / `httpx.HTTPError → 502` code paths inside `_render_get`.

Fix:
- Add 2 tests at `httpx.AsyncClient.get` level using `patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("t"))` and `httpx.HTTPError("net")`. Call `_render_get` directly via `asyncio.run(...)`; assert raised `HTTPException` status codes are 504 and 502 respectively. (Pattern in brief §Feature 2 Key Constraints already calls for this — it was missed in V0.1.)

**F4 (Gate 4 H1 + Gate 2 LOW — `allow_director=False` dead code).**
`authz.py:161-162` returns `CallerContext` immediately on `AUTH_ONLY` policy without ever consulting `allow_director`. The `allow_director=False` kwarg on both `Depends(authz(...))` calls in `render_config.py` is structurally inert; whitelist is the sole Director block.

Fix (minimum — cosmetic; pick ONE of the two):
- **Option A (preferred):** drop `allow_director=False` arg from both `Depends(authz(Policy.AUTH_ONLY))` calls. Add a 1-line comment above each: `# Director is blocked by _require_whitelist(ctx) — authz(AUTH_ONLY) does not honor allow_director.`
- **Option B:** extend `authz.py` to honor `allow_director` under AUTH_ONLY (adds an `if not allow_director and is_director: raise 403` check before the early return). Bigger diff, touches the auth surface — defer unless Director wants it now.

Default: ship Option A. Do NOT touch `authz.py` in this fold.

### Deferred (NOT in V0.2, follow-up brief candidates)

- Depends-layer whitelist via new `Policy` enum (Gates 3 MED2 + structural side of Gate 4 H1) — refactor scope; current whitelist invariant test guards widening.
- Split `/render/services/{id}/env-vars` into keys-only + per-key-audited (Gate 2 MED#3 design proposal).
- httpx client pooling (Gate 3 LOW).
- Pagination `truncated: true` flag at limit=100 (Gate 3 LOW).
- `print()` → structured logger with otel context (Gate 3 LOW).

### Acceptance criteria (V0.2)

| AC | Source | Verification |
|---|---|---|
| **A10** | F1 audit emit on env-vars reads | `test_envvars_read_emits_audit` + `test_services_read_emits_audit` GREEN; live smoke (post-merge) shows 1 `bus_audit` row per call |
| **A11** | F2 regex tightening | new tests `test_envvars_invalid_service_id_with_{query,hash,percent}` GREEN |
| **A12** | F3 httpx-level error mapping tests | new `test_render_get_timeout_maps_to_504` + `test_render_get_http_error_maps_to_502` GREEN, calling `httpx.AsyncClient.get` side_effect |
| **A13** | F4 allow_director arg dropped + comments added | grep `allow_director` in `render_config.py` returns 0 hits (in handler args) + 2 comments in place |
| **A14** | Full suite no regressions | `pytest tests/ -v` GREEN |
| **A15** | No new secret leakage paths | audit row contains slug + service_id + count, NO env-var values |

### Post-fold re-gate chain

- Gate 1: B4 pytest GREEN (literal)
- Gate 2: AH2 /security-review on V0.2 diff (focus: audit emission shape + regex tightening)
- Gate 4: AH1 feature-dev:code-reviewer 2nd-pass on V0.2 diff (Gate 3 architect cleared shape on V0.1; only re-run if F1 changes the architecture, which it should not)

### Sequencing

1. `cd ~/bm-b4-brisen-lab && git fetch origin && git checkout b4/render-config-read-1 && git pull --ff-only` (rebase if upstream b4/render-config-read-1 was force-pushed; ours has not been).
2. Read `bus.py` `make_audit_emitter` source to confirm audit shape + call signature before wiring F1.
3. Implement F1 → F2 → F3 → F4 in order. F1 is the heaviest; the rest are 1-line edits + tests.
4. `pytest tests/test_render_config.py -v` GREEN (expect ~24 tests post-fold).
5. `pytest tests/ -v` GREEN.
6. Push to `b4/render-config-read-1`. PR #9 auto-updates.
7. Ship via bus paste to /msg/lead per AH1 routing correction (NOT /msg/cowork-ah1). PL ship-report contract per SKILL.md.

### Anchors

- Director ratification: 2026-05-11 ~09:30Z "go" on AH1's V0.2 fold recommendation
- AH2 Gate 2 verdict: bus msg #72 (full body via `GET /event/72/full`)
- Gate 3 verdict: code-architecture-reviewer agent `addb10afec991e8ac`
- Gate 4 verdict: feature-dev:code-reviewer agent `a771b185e0d5c0e1f`
- AID CONTRACT v1.1 (msg #68): AH1 owns gate sequencing + fold scope per §4


# CODE_4_PENDING — BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1 — 2026-05-11

**Brief:** baker-master `briefs/BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md` (Tier B, ~2-3 hours, 9 ACs)
**Working branch:** `b4/render-config-read-1` (brisen-lab repo)
**Repo:** brisen-lab @ `~/bm-b4-brisen-lab` (NOT baker-master)
**Pre-requisites:** brisen-lab main at `8b0b7fb` or newer (sync first: `git fetch && git checkout main && git pull --ff-only`)
**Acceptance criteria:** per brief §AC table (9 testable items, A1-A9)
**Ship gate:** literal `pytest tests/test_render_config.py -v` GREEN + `pytest tests/ -v` no regressions — no "by inspection" (Lesson #8 + #52)
**Heartbeat:** 12h cadence binding (per SKILL.md §B-code stall chase)

**Read first (MANDATORY):**
1. `briefs/BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md` — full spec + 3 features + 9 ACs
2. `~/baker-vault/_ops/agents/b4/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

**Path forward:**
1. Read brief BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md cover-to-cover.
2. Sync brisen-lab: `cd ~/bm-b4-brisen-lab && git fetch origin main && git checkout main && git pull --ff-only`. Confirm HEAD `8b0b7fb` or newer.
3. Branch: `git checkout -b b4/render-config-read-1`.
4. Implement Feature 1: write `render_config.py` per brief §1.1. Edit `app.py` 2 lines per §1.2. Verify `requirements.txt` has `httpx` (add if missing per §1.3).
5. Implement Feature 2: write `tests/test_render_config.py` per brief §2.
6. Live pytest GREEN: `pytest tests/test_render_config.py -v` (must be all-green) + `pytest tests/ -v` (no regressions). Capture literal output for PR description.
7. Open PR to brisen-lab `main`. Title: `feat(render-config): read-only Render API proxy on bus surface (BRISEN_LAB_RENDER_CONFIG_READ_1)`.
8. Ship via PL paste-block per SKILL.md §"PL ship-report contract".

**NOTE:** Feature 3 (live smoke tests) + Render env-var PUT happen POST-MERGE on AH1's side. B4 ships PR + tests; AH1 handles Tier-B env-var PUT + smoke tests + AID confirmation. Do NOT attempt to set `RENDER_API_KEY` env-var yourself — that's AH1's Tier-B action.

**4-gate review chain on PR (post-B4 ship):**
- Gate 1: B4 pytest GREEN (literal output in PR)
- Gate 2: AH2 `/security-review` against diff
- Gate 3: AH1 `architecture-review` via picker-architect
- Gate 4: AH1 `feature-dev:code-reviewer` 2nd-pass (parallel with Gate 3)

**Critical do-NOTs:**
- Do NOT write any Render API key value into a source file, brief, commit message, or PR description. Key lives in 1Password only; `RENDER_API_KEY` env var is set by AH1 post-merge.
- Do NOT widen `RENDER_CONFIG_ALLOWED_SLUGS` beyond `{"aid", "lead", "deputy"}`. Director ratified that whitelist 2026-05-11; widening = new Director ask.
- Do NOT add POST/PUT/PATCH/DELETE routes to `render_config.py`. Read-only is the contract.
- Do NOT touch baker-master — this is a brisen-lab-only brief. (The brief FILE lives in baker-master/briefs/ but the implementation is brisen-lab.)

**PL ship-report:** End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract".

**Anchor:** Director ratification 2026-05-11 ~07:55Z "confirm and go" on whitelist `['aid', 'lead', 'deputy']`. AID request relayed via Director chat (msg #62 thread re: cockpit fix closure). Brief commit `<TBD>` baker-master main.

---

## Prior CODE_4 task (archive reference)

BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1 — COMPLETE 2026-05-05. brisen-lab PR #3 merged `d7c46a0`; baker-master PR #161 merged `87f0535`. Mailbox COMPLETE flip committed `693b619`. Overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
