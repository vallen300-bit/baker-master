# BRIEF: BRISEN-LAB-AUTH-COMPLETION-1 — close two gaps surfaced by V2 cutover (2026-05-05)

## Context

The 2026-05-05 V2 cutover (BRISEN_LAB_V2_ENABLED=true on Render brisen-lab service `srv-d7q7kvlckfvc739l2e8g`, deploy `dep-d7t6qfog4nts73epb28g`) landed cleanly at the daemon level. Reverse-direction cross-talk test (lead → cowork-ah1) shipped (msg_id=1, posted 22:39:17Z). But two auth gaps surfaced when the test was attempted:

- **F1 — inbox-read authorization gap.** `GET /msg/{terminal}` (`bus.py:298-349`) resolves the caller's `X-Terminal-Key` to a `reader_slug` via `auth_lab.resolve_terminal_key()`, but never checks that `reader_slug == terminal` (or that the caller is otherwise authorized to read `terminal`'s inbox). Verified: `lead`'s key successfully read `cowork-ah1`'s inbox in tonight's test. Same primitive `_require_worker_slug()` is used on `POST /msg/<terminal>` (`bus.py:170-184`) and on `POST /msg/<id>/ack` (`bus.py:433`) — both also lack equivalent recipient-bound checks. The H7 NH2 invariant ("token.worker_slug == caller's terminal-key worker_slug") holds for `ratify_decision` but not for the inbox surface.

- **F3 — partial terminal-key provisioning.** Tonight's cutover provisioned 3 worker keys on the daemon (`director`, `cowork-ah1`, `lead`) — the minimum needed for the cross-talk test. Per `HARDENING.md` H1, the design enumerates 12 workers: `director`, `cowork-ah1`, `lead`, `deputy`, `architect`, `b1`–`b5`, `cortex`, `daemon`. The remaining 9 keys are absent from the daemon's `BRISEN_LAB_TERMINAL_KEYS` JSON map. Their POST/GET/ratify_decision calls return 401 `bad_terminal_key` until provisioned.

This brief closes both gaps. F1 = code (B-code dispatchable). F3 = operations (AH1-execute; no B-code dispatch — secret distribution must stay on the orchestrator).

## Estimated time: ~1h
## Complexity: Low (F1 surgical handler edit + 1 unit test; F3 pure operations)
## Prerequisites: V2 cutover live (done 2026-05-05); 1Password CLI authenticated; Render API key in `op://Baker API Keys/API Render/credential`
## Tier: A (auth-touching surface; `feature-dev:code-reviewer` standard pass; `/security-review` SHOULD run since F1 closes a horizontal-privilege gap on auth-bearing endpoint)

---

## Feature 1 — Tighten `GET /msg/{terminal}` authorization (B-code task)

### Problem

Any worker holding a valid terminal-key can read any other worker's inbox via `GET /msg/{terminal}` by passing the target slug in the URL path. Confirmed in tonight's V2 test:

```
$ curl -H "X-Terminal-Key: $LEAD_KEY" https://brisen-lab.onrender.com/msg/cowork-ah1
{"messages": [{"id": 1, "from_terminal": "lead", "to_terminals": ["cowork-ah1"], ...}]}
```

`lead`'s key correctly resolves to `reader_slug="lead"`, but the SQL clause `clauses = ["%s = ANY(to_terminals)"]; params: list[Any] = [terminal]` filters by the **URL-path terminal**, not by the **authenticated caller**. The caller can therefore peek into any inbox addressed to anyone.

### Current state

- File: `bus.py:298-349` (handler), `bus.py:67-69` (`_require_worker_slug` helper).
- The same anti-pattern exists at `POST /msg/<id>/ack` (`bus.py:433`): a caller can ack a message they were not addressed in by passing the message's `id` in the URL.
- It does NOT exist at `POST /msg/<id>/ratify_decision` (`bus.py:477`) — that endpoint enforces NH2 ("`token.worker_slug == caller terminal-key worker_slug`").

### Implementation

**File:** `bus.py` (brisen-lab repo, branch `b<N>/brisen-lab-auth-completion-1`).

#### Edit 1 — `GET /msg/{terminal}` recipient-bound authz

Update the handler at `bus.py:298-349`. Add the authz check immediately after `reader_slug = _require_worker_slug(x_terminal_key)`:

```python
@app.get("/msg/{terminal}")
async def get_msg(terminal: str,
                  since: Optional[str] = None,
                  kind: Optional[str] = None,
                  topic: Optional[str] = None,
                  exclude_self: bool = False,
                  include_deleted: bool = False,
                  limit: int = 200,
                  x_terminal_key: str = Header(None)):
    reader_slug = _require_worker_slug(x_terminal_key)
    # Surface auth completion: caller must be the addressed terminal.
    # (broadcast-reads handled by `kind=broadcast` filter — every worker
    # receives messages with kind=broadcast independent of to_terminals.)
    if reader_slug != terminal:
        raise HTTPException(status_code=403,
                            detail="reader_slug_mismatch")
    if kind is not None and kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"bad_kind:{kind}")
    ...
```

**Why 403, not 404:** the caller authenticated successfully; they're just not authorized for *this* resource. RFC 7231 §6.5.3 — 403 is the right status for "auth OK, action denied."

**Why no broadcast escape hatch:** `kind=broadcast` messages are addressed via `to_terminals=['*']` or by being filtered server-side; the existing `to_terminals` clause already covers them once a worker registers as a broadcast listener (separate concern, not in scope here).

#### Edit 2 — `POST /msg/<id>/ack` recipient-bound authz

Update the handler at `bus.py:433`. Look up the message; require `reader_slug` ∈ `to_terminals`:

```python
@app.post("/msg/{msg_id}/ack")
async def ack_msg(msg_id: int,
                  x_terminal_key: str = Header(None)):
    acker_slug = _require_worker_slug(x_terminal_key)
    # Surface auth completion: caller must be in the message's recipients.
    def _authz_lookup():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT to_terminals FROM brisen_lab_msg "
                    "WHERE id = %s LIMIT 1",
                    (msg_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
    to_terminals = await asyncio.to_thread(_authz_lookup)
    if to_terminals is None:
        raise HTTPException(status_code=404, detail="msg_not_found")
    if acker_slug not in to_terminals:
        raise HTTPException(status_code=403,
                            detail="acker_slug_not_in_recipients")
    # ... existing ack body unchanged from bus.py:433+
```

(Read `bus.py:433` first to see the current ack body — pre-fix lookup must precede whatever logic is currently there. Don't replicate connection-pool churn — fold the new `SELECT to_terminals` into the existing `_ack()` thread function if cleanly mergeable.)

### Key constraints

- **Connection rollback discipline**: every `except` block in any new code path MUST `conn.rollback()` before re-raising or returning (project rule + Lesson #X). The new `_authz_lookup` block reads only — no rollback needed unless the SELECT raises (in which case `with get_conn() as conn:` already cleans up).
- **`LIMIT 1` on the new lookup** (per project rule on unbounded queries — even single-row PK lookups should be explicit).
- **Idempotency unchanged** — the 403 raise happens before any state mutation; the existing ack semantics (idempotent re-ack returning the same id) are untouched on the authorized path.
- **Don't touch `_require_worker_slug`** itself — it's correct as-is. The fix is in the handler bodies, not the helper.
- **Don't touch `POST /msg/<id>/ratify_decision`** — already enforces NH2; out of scope.

### Verification

#### Unit test (NEW file: `tests/test_inbox_read_authz.py`)

> **⚠️ V0.4: SUPERSEDED — see Amendment §L for the AUTHORITATIVE 8-test list.** The V0.1 numbered list below is RETAINED for audit trail only. B-code MUST implement Amendment §L's table verbatim, NOT the list below.

~~Test cases (V0.1 — DO NOT IMPLEMENT):~~
1. ~~`test_get_msg_self_succeeds` — `lead` reads `/msg/lead` → 200.~~
2. ~~`test_get_msg_other_403` — `lead` reads `/msg/cowork-ah1` → 403 with `detail="reader_slug_mismatch"`.~~
3. ~~`test_get_msg_no_key_401` — no `X-Terminal-Key` header → 401 (regression: existing behavior preserved).~~
4. ~~`test_ack_self_addressed_succeeds` — `cowork-ah1` acks a msg with `to_terminals=['cowork-ah1']` → 200.~~
5. ~~`test_ack_not_in_recipients_403` — `lead` tries to ack a msg addressed only to `cowork-ah1` → 403 with `detail="acker_slug_not_in_recipients"`.~~
6. ~~`test_ack_unknown_msg_404` — caller acks `msg_id=999999` → 404. (DROPPED in V0.3 §L — out of F1 scope.)~~

Use existing `TEST_DATABASE_URL_BRISEN_LAB` infrastructure + `conftest.py` patterns. Tests skip if env-var absent (existing convention).

#### Manual prod verification (post-merge + apply)

```
LEAD_KEY=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')
COWORK_KEY=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_cowork-ah1/credential')

# Lead reads own inbox — expect 200.
curl -sw "%{http_code}\n" -H "X-Terminal-Key: $LEAD_KEY" \
  https://brisen-lab.onrender.com/msg/lead | tail -1

# Lead tries to peek into cowork-ah1 inbox — expect 403.
curl -sw "%{http_code}\n" -H "X-Terminal-Key: $LEAD_KEY" \
  https://brisen-lab.onrender.com/msg/cowork-ah1 | tail -1

# Cowork-ah1 reads own inbox (sees message #1 from cross-talk test) — expect 200.
curl -sw "%{http_code}\n" -H "X-Terminal-Key: $COWORK_KEY" \
  https://brisen-lab.onrender.com/msg/cowork-ah1 | tail -1
```

---

## Feature 3 — Provision remaining 9 worker keys (AH1-operational)

### Problem

Daemon `BRISEN_LAB_TERMINAL_KEYS` env-var currently holds only 3 keys (`director`, `cowork-ah1`, `lead` — set 2026-05-05T22:38Z, deploy `dep-d7t72dr7uimc7386ca6g`). Per HARDENING.md H1, 12 workers are in scope. The remaining 9 (`deputy`, `architect`, `b1`–`b5`, `cortex`, `daemon`) cannot authenticate to the daemon — every call returns 401 `bad_terminal_key`.

### Why this is AH1-operational, not B-code

This task is pure secret distribution: generate 9 keys, write to Render env (merge mode), write to 1Password, update zshrc launcher functions. No code change. B-code workers are sandboxed; they should not handle Render API tokens or write to 1Password. AH1 already executed this pattern for the 3 cutover keys tonight — same pattern, 3× the volume.

### Implementation (AH1 runbook)

**Step 1 — Generate 9 keys** (one at a time, save to `/tmp/.lab_keys/<slug>` mode 600; the same pattern as the 3-key bootstrap):

```python
import secrets, json, os
slugs = ['deputy', 'architect', 'b1', 'b2', 'b3', 'b4', 'b5', 'cortex', 'daemon']
keys = {slug: secrets.token_urlsafe(32) for slug in slugs}
os.makedirs('/tmp/.lab_keys', exist_ok=True)
os.chmod('/tmp/.lab_keys', 0o700)
for slug, key in keys.items():
    p = f'/tmp/.lab_keys/{slug}'
    with open(p, 'w') as f:
        f.write(key)
    os.chmod(p, 0o600)
```

**Step 2 — Update Render daemon env-var (MERGE 9 NEW KEYS into existing 3)**

CRITICAL: must NOT clobber existing 3 keys. Read current value first, merge, then write back.

```bash
# Read current map
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
CURRENT_JSON=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/env-vars?limit=100" \
  | python3 -c "import sys,json; data=json.load(sys.stdin); print([d['envVar']['value'] for d in data if d['envVar']['key']=='BRISEN_LAB_TERMINAL_KEYS'][0])")

# Merge new keys into existing JSON
MERGED=$(python3 -c "
import json, os
existing = json.loads('''$CURRENT_JSON''')
for slug in ['deputy', 'architect', 'b1', 'b2', 'b3', 'b4', 'b5', 'cortex', 'daemon']:
    with open(f'/tmp/.lab_keys/{slug}') as f:
        existing[slug] = f.read().strip()
print(json.dumps(existing))
")
```

Then push via Render MCP `update_environment_variables` (merge mode — Render rule: never raw PUT):

```
mcp__render__update_environment_variables(
    serviceId='srv-d7q7kvlckfvc739l2e8g',
    envVars=[{'key': 'BRISEN_LAB_TERMINAL_KEYS', 'value': '<MERGED JSON>'}]
)
```

**Step 3 — Write 9 1Password items** (vault: `Baker API Keys`, naming pattern matches the 3 already created):

```bash
for slug in deputy architect b1 b2 b3 b4 b5 cortex daemon; do
  KEY=$(cat /tmp/.lab_keys/$slug)
  TITLE="BRISEN_LAB_TERMINAL_KEY_$slug"
  if op item get "$TITLE" --vault='Baker API Keys' >/dev/null 2>&1; then
    op item edit "$TITLE" --vault='Baker API Keys' "credential[password]=$KEY" >/dev/null
  else
    op item create --category='API Credential' --vault='Baker API Keys' \
      --title="$TITLE" "credential[password]=$KEY" >/dev/null
  fi
done
```

(NB: 1Password secret references reject parens; titles must use `_<slug>`, not `(<slug>)`.)

**Step 4 — Update zshrc launcher functions** to source each key from 1Password.

Edit `~/.zshrc`. For each launcher (`b1`, `b2`, `b3`, `b4`, `b5`, `aihead2`), add `BRISEN_LAB_TERMINAL_KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_<slug>/credential' 2>/dev/null)"` before `claude`. Pattern (same as `aihead1` already updated tonight):

```bash
function b1() {
  cd ~/bm-b1 && printf "\033]0;B1\007"
  BAKER_ROLE=b1 FORGE_TERMINAL=b1 \
  BRISEN_LAB_TERMINAL_KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_b1/credential' 2>/dev/null)" \
  claude "$@"
}
```

(Apply same pattern for b2, b3, b4, b5, aihead2 → maps to slug `deputy`. `architect`, `cortex`, `daemon` slugs have no shell launcher today; their keys live only in 1Password + Render until launcher integration is needed.)

**ALSO:** lower-case `BAKER_ROLE`. Tonight's cutover surfaced that `BAKER_ROLE=B1` is upper-case but `baker_mcp_server.py:1155` does `os.getenv('BAKER_ROLE', '').strip().lower()` → `'b1'` (matches daemon worker_slug). The current `BAKER_ROLE=B1` actually works because of the `.lower()`. No change needed unless future code drops the lower-case. Leave as-is for compatibility.

**Step 5 — Cleanup**

```bash
rm -rf /tmp/.lab_keys
```

**Step 6 — Verification**

```bash
# 1. Render daemon env-var contains all 12 keys
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/env-vars?limit=100" \
  | python3 -c "import sys,json; data=json.load(sys.stdin); raw=[d['envVar']['value'] for d in data if d['envVar']['key']=='BRISEN_LAB_TERMINAL_KEYS'][0]; print('slugs:', sorted(json.loads(raw).keys()))"
# Expect: ['architect', 'b1', 'b2', 'b3', 'b4', 'b5', 'cortex', 'cowork-ah1', 'daemon', 'deputy', 'director', 'lead']

# 2. Sample auth from b1's key (after starting fresh `b1` shell — env-var only loads on aihead1/b1/etc launcher)
B1_KEY=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_b1/credential')
curl -sw "%{http_code}\n" -H "X-Terminal-Key: $B1_KEY" \
  https://brisen-lab.onrender.com/msg/b1 | tail -1
# Expect: 200 (post-F1 merge: also confirms b1 reads only its own inbox)

# 3. 1Password vault inventory
op item list --vault='Baker API Keys' | grep BRISEN_LAB_TERMINAL_KEY
# Expect: 12 items
```

### Key constraints

- **Render env merge mode** (project rule): never PUT all env vars — only merge new keys. Verified tonight that merge preserves `DATABASE_URL`, `FORGE_KEY`, `ALLOWED_ORIGINS`, `BRISEN_LAB_V2_ENABLED`.
- **1Password secret reference shape**: paths must NOT contain parens (op CLI rejects). Use `_<slug>` not `(<slug>)`.
- **Tmp file mode 600**, parent dir 700 — short-lived (~5 min). Cleanup is mandatory; tmp-file leakage is the single highest-impact failure mode here.
- **Don't echo keys to chat** — keep them in subshell env / file vars only. The 3-key bootstrap had to expose values via `cat _aggregate.json` for the MCP call; this 9-key step has the same risk if not careful. Prefer Render MCP merge-mode (which does NOT echo back) over Render API curl.
- **Daemon redeploy on env-var change**: Render auto-triggers a deploy. Wait for `live` status before declaring done (45-60s typically).
- **Don't ship Feature 3 before Feature 1** lands and is verified — F1 closes the inbox-read horizontal-privilege hole; once 9 more workers can read, the blast radius of F1 absent is 12× wider. Sequencing matters.

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | `bus.py` GET `/msg/{terminal}` raises 403 when `reader_slug != terminal` (V0.4: 8-test list per §L; broadcast OR-branch verified per §K) | grep + 8 unit tests in `test_inbox_read_authz.py` |
| **A2** | `bus.py:442-463` existing `_is_director` ack-authz path REGRESSION-VERIFIED unchanged (V0.4: per §F — Edit 2 was struck) | grep + tests 5+6+8 |
| **A3** | All 8 unit tests pass on `TEST_DATABASE_URL_BRISEN_LAB` (V0.4: 8 not 6 — per §L+§M) | literal pytest output |
| **A4** | Existing brisen-lab test suite unchanged (no regressions) | full pytest run |
| **A5** | Manual prod verification: `lead` → `/msg/cowork-ah1` returns 403 | curl one-liner output |
| **A6** | Manual prod verification: `lead` → `/msg/lead` returns 200 | curl one-liner output |
| **A7** | F3 — Render `BRISEN_LAB_TERMINAL_KEYS` JSON has all 12 slugs | env-var inspection (script in Step 6) |
| **A8** | F3 — 12 1Password items exist (`BRISEN_LAB_TERMINAL_KEY_<slug>` pattern) | `op item list` |
| **A9** | F3 — `b1` launcher in `~/.zshrc` sources its key via `op read` | grep `~/.zshrc` |
| **A10** | F3 — sample test: fresh `b1` shell → `mcp__baker__baker_inbox_post(to='lead', ...)` succeeds | manual test on next b1 session |
| **A11** | Tmp dir `/tmp/.lab_keys` deleted after operations | `[ ! -d /tmp/.lab_keys ]` |
| **A12** | `feature-dev:code-reviewer` standard pass on F1 PR | reviewer verdict |
| **A13** | `/security-review` standard pass on F1 PR | reviewer verdict — auth-touching, mandatory |

**Ship gate:** A1–A6 all green AND `/security-review` clean → F1 merges. F3 gates on F1 merge (sequencing rule).

---

## Files Modified (F1)

- `bus.py` (brisen-lab) — 2 handler edits (`get_msg`, `ack_msg`); new authz checks.
- `tests/test_inbox_read_authz.py` (brisen-lab, NEW) — 6 unit tests.

## Files Modified (F3)

- Render env-var `BRISEN_LAB_TERMINAL_KEYS` (out-of-repo).
- 1Password vault `Baker API Keys` (9 new items).
- `~/.zshrc` (out-of-repo, MacBook-local) — 6 launcher functions updated.

## Do NOT Touch

- `auth_lab.py` `_require_worker_slug` — correct as-is; only handler-level checks change.
- `bus.py` `POST /msg/{terminal}` — already enforces sender-binding via `from_terminal = sender_slug` (line 184).
- `POST /msg/<id>/ratify_decision` — H7 NH2 already covers this surface.
- `freeze.py` — out of scope; V2_ENABLED gate is independent.

---

## Quality Checkpoints (post-deploy)

1. F1: 403 on cross-terminal inbox read attempt — verified via curl to prod.
2. F1: `/security-review` verdict pasted in PR.
3. F3: Render daemon env-var diff log — only `BRISEN_LAB_TERMINAL_KEYS` value changed; other keys (DATABASE_URL etc.) untouched.
4. F3: confirm 1Password vault count matches expected 12.
5. F3: tmp dir cleaned.
6. After both F1+F3 land: re-run V2 cross-talk test from b1 (post-launcher-update) to verify the full happy-path now lands at `/msg/<self>` 200 + can post to `/msg/lead` from b1's key.

---

## Sequencing

1. B-code claims brief; reads cover-to-cover (including ALL amendments — V0.2/V0.3/V0.4 instructions are AUTHORITATIVE over V0.1 body).
2. EXPLORE (V0.4: per §A struck Edit 2; per §K added broadcast OR-branch verification gate): re-read `bus.py:298-349` (GET handler) + `bus.py:442-463` (existing ack-authz, do NOT modify). **Verify broadcast SQL OR-branch at bus.py:330-340 per §K — Variant A (present) or Variant B (absent).** If Variant B, Edit 1 expands per §K. NO `_authz_lookup` block (struck per §A).
3. WRITE: F1 handler edit (GET only — single edit per §A) + 8 unit tests per §L+§M.
4. Local pytest GREEN against `TEST_DATABASE_URL_BRISEN_LAB`.
5. Open PR. AH1 reviews + runs `/security-review`. After PASS, AH1 merges.
6. AH1 verifies F1 in prod via curl one-liners (Quality Checkpoints §1).
7. AH1 executes F3 runbook (Steps 1–6 above) — operationally, no PR.
8. AH1 verifies F3 (A7–A11).
9. AH1 reports closure to Director; brief CAPTURE phase: append any improvisation lessons to `tasks/lessons.md`.

---

## Open questions for AH1 (to surface to Director)

None expected. F1 is a surgical recipient-binding check; F3 is identical to tonight's 3-key bootstrap with 3× volume.

If F1 surfaces an `_ack()` body that already does its own message lookup, the `_authz_lookup` block can be folded into the existing thread — no new connection-pool churn. B-code uses judgment here; surface to AH1 only if integration is non-obvious.

---

## Reference

- bus.py GET handler: `bus.py:298-349` (no recipient-bound authz)
- bus.py ack handler: `bus.py:433` (no recipient-bound authz)
- bus.py ratify_decision handler: `bus.py:477` (correctly enforces NH2)
- auth_lab.py terminal-key resolution: `auth_lab.py:48-86`
- HARDENING.md H1 vault layout: 12 worker scope
- Cutover-runbook: `_ops/processes/v2-bridge-cutover-runbook.md` (baker-vault main `1c762b3`)
- Tonight's 3-key bootstrap pattern: this session's reverse-direction test transcript
- Migration immutability rule: `tasks/lessons.md` Lesson #50 (not directly relevant — no migrations here, but reinforces "verify via Render API after env-var write")

---

# V0.2 Amendment — Architect-reviewer fold (2026-05-05)

> **Trigger:** post-WRITE architect-reviewer pass surfaced one HIGH fact-error and one HIGH design gap. Folding before B-code dispatch.

## Amendment §A — STRIKE Edit 2 (ack authz already exists)

**Reviewer finding (HIGH, confidence high):** `bus.py` lines 442-463 already implement the recipient-bound authz check on `POST /msg/{msg_id}/ack`. The current code:
- selects `to_terminals` + `acknowledged_at` from `brisen_lab_msg` (line 445-449)
- checks `if slug not in (to_terminals or []) and not _is_director(slug)` (line 454)
- returns HTTP 403 `not_recipient` (line 469) — including a `_is_director(slug)` exemption that the V0.1 proposed code DROPPED.

**Action:** Edit 2 in V0.1 is REMOVED from scope. The brief's previously-proposed `_authz_lookup` block + 409-handler-style refactor would have:
1. Duplicated existing enforcement (wasted B-code time).
2. Silently regressed by dropping the `_is_director` bypass (director-slug holders need to ack other terminals' messages for moderation flows).

**Replacement:** the only `bus.py` edit in F1 is now Edit 1 — `GET /msg/{terminal}` recipient-bound authz. AC A2 / unit tests 4–5 are converted from "test new code" to "regression-verify the existing `_ack` 403 path still holds + the `_is_director` exemption is preserved."

## Amendment §B — Broadcast handling for `GET /msg/{terminal}`

**Reviewer finding (HIGH, confidence high):** the V0.1 fix (`if reader_slug != terminal: raise 403`) silently drops broadcast messages. The codebase convention is `to_terminals=['*']` (verified at `bus.py` line 135 + tests at line 38). There is no server-side fanout that copies `'*'`-addressed rows into per-worker inboxes — the existing GET handler relies on `'*' = ANY(to_terminals)` matching when callers query their own inbox.

**Action:** the V0.1 SQL filter `clauses = ["%s = ANY(to_terminals)"]` already matches `'*'`-addressed messages when the caller queries their own slug. The 403 gate must NOT block self-reads, so it stays as-is, BUT the GET handler must explicitly preserve broadcast-read semantics for self-queries (no change needed; the F1 fix already only matters when `reader_slug != terminal`, which is the cross-terminal-peek case, not the self-broadcast-read case).

**Verification clarification:** add a new test case (replacing original `test_get_msg_other_403`):

```python
def test_get_msg_self_broadcast_succeeds(...):
    # Setup: post a message with to_terminals=['*'] from director
    # Caller: lead reads /msg/lead with X-Terminal-Key=lead's
    # Expect: 200 + broadcast message in result list
```

This catches the regression risk (404/403 on self-broadcast read).

## Amendment §C — Add explicit cross-slug attack test

**Reviewer finding (MED, confidence high):** the V0.1 unit-test surface lacks the actual F1 attack scenario — a non-target worker's valid key trying to read another's inbox. The 6 tests use `lead` and `cowork-ah1`; need an explicit case where `b2` (or any non-co-located slug) attempts to read `lead`'s inbox.

**Action:** add test 7 to `tests/test_inbox_read_authz.py`:

```python
def test_get_msg_cross_slug_attack_403(...):
    # Setup: provision keys for both lead and a third slug, e.g. b2
    # Caller: b2's key, GET /msg/lead
    # Expect: 403 with detail="reader_slug_mismatch"
```

Updated AC A1 to require all 7 tests pass.

## Amendment §D — F3 merge script shell-injection hardening

**Reviewer finding (MED, confidence medium):** the V0.1 step-2 heredoc pattern `python3 -c "... json.loads('''$CURRENT_JSON''')"` is fragile to single-quotes inside the JSON value (improbable for urlsafe tokens, but a footgun). Replace with file-based round-trip:

```bash
RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
# Read existing map → /tmp/.lab_keys/_existing.json
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/env-vars?limit=100" \
  | python3 -c "
import sys, json, os
data = json.load(sys.stdin)
existing_raw = [d['envVar']['value'] for d in data if d['envVar']['key']=='BRISEN_LAB_TERMINAL_KEYS'][0]
with open('/tmp/.lab_keys/_existing.json', 'w') as f:
    f.write(existing_raw)
os.chmod('/tmp/.lab_keys/_existing.json', 0o600)
"

# Merge new keys with existing (file-based, no shell interpolation of values)
python3 - <<'PYEOF'
import json, os
with open('/tmp/.lab_keys/_existing.json') as f:
    existing = json.loads(f.read().strip())
for slug in ['deputy', 'architect', 'b1', 'b2', 'b3', 'b4', 'b5', 'cortex', 'daemon']:
    with open(f'/tmp/.lab_keys/{slug}') as f:
        existing[slug] = f.read().strip()
with open('/tmp/.lab_keys/_merged.json', 'w') as f:
    json.dump(existing, f)
os.chmod('/tmp/.lab_keys/_merged.json', 0o600)
PYEOF

# Push merged JSON via Render MCP merge mode (read value from file at call site)
# AH1: invoke mcp__render__update_environment_variables with envVars=[{
#   "key": "BRISEN_LAB_TERMINAL_KEYS",
#   "value": <contents of /tmp/.lab_keys/_merged.json>
# }]
```

## Amendment §E — Explicit launcher snippets for `aihead2` (deputy) + `director`

**Reviewer finding (MED, confidence high):** `aihead2 → deputy` slug mapping was a parenthetical in V0.1; reviewer flagged this as not-validateable by B-code without the actual zshrc entry. Director slug had no launcher mention at all.

**Action — explicit launcher updates for F3 Step 4:**

```bash
function aihead2() {
  cd ~/Desktop/baker-code && BAKER_ROLE=deputy FORGE_TERMINAL=deputy \
    BRISEN_LAB_TERMINAL_KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_deputy/credential' 2>/dev/null)" \
    GIT_AUTHOR_NAME="AI Head B" GIT_AUTHOR_EMAIL="ah2@brisengroup.com" \
    GIT_COMMITTER_NAME="AI Head B" GIT_COMMITTER_EMAIL="ah2@brisengroup.com" \
    claude --name "AI Head B" --append-system-prompt "..." "$@"
}
```

(Replace `BAKER_ROLE=AH2` with `BAKER_ROLE=deputy` — same lower-case-matches-slug rationale that fixed `aihead1` in tonight's session.)

**Director slug:** there is NO `director()` launcher function in `~/.zshrc` today. The director slug is implicit (Director runs Cowork on his MacBook, not a Claude Code shell). Director's terminal-key is needed for ratify_decision flows initiated from Cowork, NOT a Mac terminal launcher. **Out of scope for F3 Step 4.** Director can populate `BRISEN_LAB_TERMINAL_KEY_director` via Cowork launch config if/when the ratify_decision flow needs it.

## Amendment §F — Updated Acceptance Criteria deltas

**Replaced:**
- AC A2: "raises 403 when `acker_slug not in to_terminals`" → "REGRESSION-verify existing `bus.py:442-463` 403 path holds; existing `_is_director` exemption preserved"
- AC A3: 6 tests → **7 tests** (added cross-slug attack test)

**Unchanged:** A1, A4, A5, A6, A7, A8, A9, A10, A11, A12, A13.

## Amendment §G — Net effect summary

- **Files changed (F1):** `bus.py` — 1 handler edit (GET only), not 2. `tests/test_inbox_read_authz.py` — 7 tests, not 6 (one is a regression-only test for existing ack behavior).
- **F3 hardened:** file-based JSON round-trip + explicit aihead2 launcher snippet + director-slug scoped out.
- **Risk delta:** lower than V0.1 — eliminated dead-work proposal that would have regressed `_is_director` ack exemption.
- **Brief intent (close horizontal-privilege gap on inbox-read + complete 12-key provisioning) preserved.**

**End V0.2 amendment.**

---

# V0.3 Amendment — Pre-dispatch code-reviewer fold (2026-05-06)

> **Trigger:** AH1-App-spawned `feature-dev:code-reviewer` 2nd-pass on V0.2 returned VERDICT FAIL (1 CRITICAL + 3 HIGH + 1 MEDIUM). Folding before re-dispatch. Reviewer agent ID: `a0732361a346047eb`.

## Amendment §J — CRITICAL: Render env-var paginated GET (limit=50 → limit=100)

**Reviewer finding (CRITICAL, confidence high):** F3 Step 2 + Amendment §D both call `?limit=50` on `/v1/services/{id}/env-vars`. Per `feedback_render_envvar_paginated_put.md`, Render env-var API paginates and the daemon may have ≥50 vars (DATABASE_URL, FORGE_KEY, BRISEN_LAB_TERMINAL_KEYS, BRISEN_LAB_V2_ENABLED, ALLOWED_ORIGINS, plus per-deploy + framework defaults). If `BRISEN_LAB_TERMINAL_KEYS` falls past index 50, the merge step reads it as missing → silently writes a fresh JSON containing ONLY the 9 new keys → CLOBBERS the 3 keys (lead/director/cowork-ah1) provisioned 2026-05-05.

**Action — replace ALL THREE `?limit=50` calls with `?limit=100` (V0.4: applied IN-PLACE at lines 182, 251, 422):**

V0.1/V0.2 F3 Step 2 (line ~182):
```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/env-vars?limit=100" \
```

V0.2 Amendment §D (line ~422):
```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/env-vars?limit=100" \
```

V0.1/V0.2 F3 Step 6 verification (line ~251):
```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/env-vars?limit=100" \
```

(All three Render env-var GETs must use `?limit=100`. If the env-var count ever exceeds 100, escalate — Render API supports pagination cursor; this brief does not handle that case because we are below it today.)

## Amendment §K — HIGH (a): explicit broadcast SQL OR-branch verification + DB-seeded test

**Reviewer finding (HIGH, confidence high):** V0.2 Amendment §B asserts that the existing SQL `clauses = ["%s = ANY(to_terminals)"]` covers `'*'` self-broadcast reads. This claim is unverified — if `to_terminals=['*']` (the broadcast convention) is stored in the DB but the SQL filter is `WHERE %s = ANY(to_terminals)` with `params=[reader_slug]`, the match is `'lead' = ANY(['*'])` which is FALSE. Broadcast reads are then DROPPED post-V0.1 fix.

**Action — make EXPLORE step (Sequencing §2) require explicit verification:**

Replace V0.2 Sequencing §2 with:

> 2. **EXPLORE — verification gate (auth-touching trigger):**
>    - Re-read `bus.py:298-349` (GET handler) + `bus.py:442-463` (existing ack authz).
>    - **Verify the broadcast OR-branch:** read the SQL clause-builder around `bus.py:330-340`. Confirm whether the `to_terminals` filter is:
>      - **PRESENT (Variant A):** clause includes `OR '*' = ANY(to_terminals)` → `'*'`-broadcast reads work today; only F1's recipient-bind check is needed.
>      - **ABSENT (Variant B):** clause is bare `%s = ANY(to_terminals)` → `'*'`-broadcast reads DO NOT match self-queries today; F1 fix must extend the clause to add the OR-branch alongside the recipient-bind check.
>    - **If Variant B:** Edit 1 expands to:
>      ```python
>      if reader_slug != terminal:
>          raise HTTPException(status_code=403, detail="reader_slug_mismatch")
>      # ... in the SQL clause-builder section, change the to_terminals filter from:
>      clauses = ["%s = ANY(to_terminals)"]
>      params: list[Any] = [terminal]
>      # to:
>      clauses = ["(%s = ANY(to_terminals) OR '*' = ANY(to_terminals))"]
>      params: list[Any] = [terminal]
>      ```
>    - **DB-seeded assertion in `test_get_msg_self_broadcast_succeeds`:**
>      - Setup: post a message with `to_terminals=['*']` from director's terminal-key (verify via direct INSERT into `brisen_lab_msg` if test infra allows; else POST via daemon test client).
>      - Caller: `lead`'s key, GET `/msg/lead`.
>      - Expect: 200 + the broadcast message in result list (id matches the seeded row).
>      - This test FAILS in Variant B until the OR-branch is added — making the SQL gap visible at test time, not at production-broadcast time.
>    - Surface the variant determination to AH1 in PR body before merge.

## Amendment §L — HIGH (b): explicit final 7-test list

**Reviewer finding (HIGH, confidence high):** V0.2 §B replaces test 2 (`test_get_msg_other_403`) with `test_get_msg_self_broadcast_succeeds`, but V0.2 §C *adds* `test_get_msg_cross_slug_attack_403`. The combined test count becomes ambiguous (6? 7? 8?) because §B says "replacing" while §C says "adding test 7." The two amendments don't compose cleanly.

**Action — state the final ordered 7-test list explicitly. This SUPERSEDES all prior test enumerations (V0.1 §Verification + V0.2 §B + V0.2 §C):**

`tests/test_inbox_read_authz.py` MUST contain exactly these 7 tests, in this order:

| # | Test name | Setup | Caller | Expect |
|---|-----------|-------|--------|--------|
| 1 | `test_get_msg_self_succeeds` | post msg `to_terminals=['lead']` from director | lead's key, GET `/msg/lead` | 200 + msg in list |
| 2 | `test_get_msg_cross_terminal_403` | post msg `to_terminals=['cowork-ah1']` from lead | lead's key, GET `/msg/cowork-ah1` | 403 `detail="reader_slug_mismatch"` |
| 3 | `test_get_msg_no_key_401` | (no setup) | no `X-Terminal-Key` header, GET `/msg/lead` | 401 (regression — existing behavior) |
| 4 | `test_get_msg_self_broadcast_succeeds` | DB-seeded msg `to_terminals=['*']` from director | lead's key, GET `/msg/lead` | 200 + broadcast msg in list (Amendment §K) |
| 5 | `test_ack_self_addressed_succeeds` | post msg `to_terminals=['cowork-ah1']` from lead | cowork-ah1's key, POST `/msg/<id>/ack` | 200 (regression — existing `_is_director` exemption preserved) |
| 6 | `test_ack_not_in_recipients_403` | post msg `to_terminals=['cowork-ah1']` from lead | lead's key, POST `/msg/<id>/ack` | 403 (regression — existing path holds) |
| 7 | `test_get_msg_cross_slug_attack_403` | post msg `to_terminals=['lead']` from director; **third-slug key created INLINE in test** (`secrets.token_urlsafe(32)` + insert into test DB worker registry — DO NOT read from env, otherwise test fails with 401 not 403 = wrong signal) | inline-created third-slug key (e.g. `b2-test`), GET `/msg/lead` | 403 `detail="reader_slug_mismatch"` |

**Director-exemption test moved to Amendment §M (test 8 — MEDIUM).**

V0.1 `test_ack_unknown_msg_404` is DROPPED — it tests existing pre-V0.1 ack behavior unrelated to F1 (msg_not_found is daemon-internal robustness, not auth surface). If brisen-lab repo wants this coverage, spin separately.

AC A3 updates from "all 6 unit tests pass" → "all 7 unit tests pass" (or 8 if Amendment §M lands).

## Amendment §M — MEDIUM: director exemption regression test

**Reviewer finding (MEDIUM, confidence high):** V0.2 §A noted the existing `_is_director(slug)` exemption at `bus.py:454` — director-slug holders ack messages addressed to other terminals (moderation flow). V0.2 §F renames AC A2 to "REGRESSION-verify existing 403 path holds; existing `_is_director` exemption preserved" but provides NO test for the exemption itself. The 7-test list above tests the deny path, not the allow path.

**Action — add test 8 to `tests/test_inbox_read_authz.py`:**

| 8 | `test_ack_director_exemption_succeeds` | post msg `to_terminals=['cowork-ah1']` from lead | director's key, POST `/msg/<id>/ack` | 200 (`_is_director` exemption preserved) |

This guards against silent regression if a future PR strips the exemption "for security" without realizing moderation flows depend on it.

AC A3 updates: "all 8 unit tests pass."

## Amendment §N — HIGH (c): F3 Step 2a — post-merge verification gate

**Reviewer finding (HIGH, confidence high):** V0.1 F3 sequencing has a gap between Step 2 (Render MCP merge) and Step 3 (1Password loop). If the MCP merge silently fails or partially succeeds, the 1Password loop runs against a daemon that isn't accepting the new keys. Worse: if the merge clobbers existing keys (e.g., Render API edge case where merge mode regresses to PUT), the 1Password write succeeds but the daemon now rejects director/cowork-ah1/lead.

**Action — insert F3 Step 2a between Step 2 and Step 3:**

> **Step 2a (NEW — post-merge verification gate)**
>
> Immediately after `mcp__render__update_environment_variables` returns success, BEFORE writing any 1Password items, verify the daemon's env-var contains the expected slug count:
>
> ```bash
> RENDER_API_KEY=$(op read 'op://Baker API Keys/API Render/credential')
> EXPECTED_COUNT=12  # 3 existing + 9 new
> ACTUAL_SLUGS=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
>   "https://api.render.com/v1/services/srv-d7q7kvlckfvc739l2e8g/env-vars?limit=100" \
>   | python3 -c "
> import sys, json
> data = json.load(sys.stdin)
> raw = [d['envVar']['value'] for d in data if d['envVar']['key']=='BRISEN_LAB_TERMINAL_KEYS'][0]
> slugs = sorted(json.loads(raw).keys())
> print(' '.join(slugs))
> ")
> ACTUAL_COUNT=$(echo "$ACTUAL_SLUGS" | wc -w | tr -d ' ')
>
> if [ "$ACTUAL_COUNT" -ne "$EXPECTED_COUNT" ]; then
>   echo "FAIL: expected $EXPECTED_COUNT slugs, got $ACTUAL_COUNT: $ACTUAL_SLUGS"
>   echo "STOP — do not proceed to Step 3 (1Password write). Escalate to Director."
>   exit 1
> fi
>
> # Also verify all 12 expected slugs are present (catches case where merge dropped one)
> EXPECTED_SLUGS="architect b1 b2 b3 b4 b5 cortex cowork-ah1 daemon deputy director lead"
> if [ "$ACTUAL_SLUGS" != "$EXPECTED_SLUGS" ]; then
>   echo "FAIL: slug set mismatch"
>   echo "Expected: $EXPECTED_SLUGS"
>   echo "Actual:   $ACTUAL_SLUGS"
>   echo "STOP — do not proceed to Step 3. Escalate to Director."
>   exit 1
> fi
>
> echo "PASS: 12 slugs present on daemon. Proceeding to 1Password write."
> ```
>
> If this gate fires STOP: revert the Render env to the pre-merge value (Render dashboard rollback or re-MCP-merge with the cached `_existing.json`), surface to Director, then resume from Step 1 with diagnosis. DO NOT write 1Password items if the daemon is in a bad state.
>
> **CRITICAL (V0.4) — Step 5 cleanup interaction:** Step 5 (`rm -rf /tmp/.lab_keys`) MUST NOT run if Step 2a returned non-zero. Before Step 2a, copy `_existing.json` to a non-temp location for rollback safety:
>
> ```bash
> # BEFORE Step 2a runs — preserve rollback artifact outside /tmp
> mkdir -p ~/.baker-rollback
> chmod 700 ~/.baker-rollback
> cp /tmp/.lab_keys/_existing.json ~/.baker-rollback/brisen_lab_terminal_keys_premerge_$(date -u +%Y%m%dT%H%M%SZ).json
> chmod 600 ~/.baker-rollback/brisen_lab_terminal_keys_premerge_*.json
> echo "Rollback artifact saved: $(ls -la ~/.baker-rollback/ | tail -1)"
> ```
>
> Then if Step 2a fires STOP, the rollback file survives even if `/tmp/.lab_keys` is wiped. Step 5 cleanup of `/tmp/.lab_keys` proceeds ONLY on Step 2a PASS. Manual cleanup of `~/.baker-rollback/` happens after AC A11 verification (after the deploy is verified live for 24h).

This gate makes the failure mode loud: a clobber would manifest as `ACTUAL_COUNT != 12` BEFORE 1Password is touched, leaving 1Password in a recoverable state.

AC A7 updates: "Render `BRISEN_LAB_TERMINAL_KEYS` JSON has all 12 slugs **AND Step 2a verification gate passed**."

## Amendment §O — Updated Acceptance Criteria summary

**Updated:**
- AC A3: "all 7 unit tests pass" → **"all 8 unit tests pass"** (7 from §L + 1 from §M).
- AC A7: amended to require Step 2a verification gate pass.

**New:**
| **A14** | F1 EXPLORE pass surfaced broadcast SQL variant determination in PR body | grep PR body for "Variant A" or "Variant B" |
| **A15** | F3 Step 2a verification gate output captured in actions log | grep `~/baker-vault/_ops/agents/ai-head/actions_log.md` |

**Unchanged:** A1, A2 (regression-only per V0.2 §F), A4, A5, A6, A8, A9, A10, A11, A12, A13.

## Amendment §P — Net effect summary

- **Pagination CRITICAL fix:** all 3 Render env-var GETs use `?limit=100`, eliminating silent-clobber risk.
- **Broadcast SQL HIGH fix:** EXPLORE step explicitly verifies OR-branch presence; if absent, F1 fix expands to add it; DB-seeded test catches gap.
- **Test list HIGH fix:** explicit ordered 8-test list supersedes all prior enumerations.
- **F3 verification gate HIGH fix:** Step 2a between merge and 1Password write makes silent failures loud.
- **Director exemption MEDIUM fix:** test 8 guards moderation-flow regression.
- **Brief intent (close horizontal-privilege gap on inbox-read + complete 12-key provisioning) preserved.**

**End V0.3 amendment.**
