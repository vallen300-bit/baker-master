# B4 ship report — BUS_POST_ENVELOPE_ID_MINT_1 (flag-flip step 1)

- **Brief:** `BRIEF_BUS_POST_ENVELOPE_ID_MINT_1` (deputy dispatch #10089, lead GO #10086)
- **Repo:** baker-master
- **Branch:** `b4/bus-post-envelope-id-mint-1`
- **Effort:** LOW
- **Goal:** every script that POSTs a *body* to the bus mints a per-send envelope id
  (`idempotency_key`), so lead can safely flip `BRISEN_LAB_REQUIRE_ENVELOPE_ID` (step 2)
  without any body-POST hard-400ing `missing_envelope_id`.

## Key finding — primary ask was already satisfied

`scripts/bus_post.sh` **and** `scripts/bus_post.py` already mint a unique `idempotency_key`
per send (uuidgen → `uuid.uuid4()` fallback), honor a `BUS_IDEMPOTENCY_KEY` env override +
`--idempotency-key` flag, and stay byte-identical otherwise. This landed under
`AGENT_BUS_IDEMPOTENT_POST_1` (commits `3f27ffa9` + `5032dc09`). So the brief's headline
"make bus_post.sh mint" is a **no-op** — no change needed there.

The load-bearing work of step 1 was therefore the **sibling-script audit**: finding any
*other* script that POSTs a message body without an id. That surfaced exactly one gap.

## Change (the one real gap)

`scripts/forge_drift_check.sh` POSTs a `kind=dispatch` **body** to `/msg/lead` with no
`idempotency_key`. The curl is best-effort (`|| true` + `>/dev/null 2>&1`), so once
`REQUIRE_ENVELOPE_ID` flips, the daemon's `missing_envelope_id` 400 would be swallowed and
the drift alert would silently vanish — the same silent-failure class already noted for the
`bad_kind` trap (codex G3 #5653). Fix: mint `"idempotency_key": str(uuid.uuid4())` into the
payload (fresh per invocation → unique → distinct drift posts never false-dedup).

- `scripts/forge_drift_check.sh` — add minted envelope id to the drift-post payload + comment.
- `tests/test_forge_drift_check.sh` — add `envelope-id-minted` assertion (present + non-blank)
  to the existing "drift post payload valid" check, regression-guarding the flag-flip safety.

## Sibling-script audit — every script that touches `/msg`, in/out with reason

**IN (POSTs a body → dedup applies → must mint an envelope id):**
| Script | Status |
|---|---|
| `scripts/bus_post.sh` | ✅ already mints (`AGENT_BUS_IDEMPOTENT_POST_1`) — no change |
| `scripts/bus_post.py` | ✅ already mints — no change |
| `scripts/forge_drift_check.sh` | ⚠️→✅ **fixed this PR** (was the only gap) |

**OUT — ack-only POSTs (`POST /msg/<id>/ack`, no body, no dedup → no id needed):**
`scripts/ack_dispatch_msgs.sh`, `scripts/codex-ack-inbox.sh`, `scripts/codexarch-ack-inbox.sh`.
Confirmed: ack path carries no body; the daemon has no body-dedup on it.

**OUT — GET-only read helpers (untouched):**
`scripts/check_inbox.sh`, `scripts/check-codex-inbox.sh`, `scripts/check-codexarch-inbox.sh`,
`scripts/read_message.sh`.

**OUT — POST to non-`/msg` endpoints (not bus messages, no envelope contract):**
`scripts/forge-agent/heartbeat-ticker.sh` (`POST /api/heartbeat`),
`scripts/forge-agent/turn-start-hook.sh` (`/api/heartbeat`),
`scripts/forge-agent/turn-stop-hook.sh` (`/api/heartbeat`),
`scripts/forge-agent/session-start-hook.sh` (`/api/register`).

**OUT — matched `/msg`/`POST` grep but unrelated:**
`scripts/cortex_rollback_v1.sh` (no `/msg` POST), `scripts/run_kbl_eval.py` (`POST` is to a
local Ollama `/api/generate`, not the bus).

No silent omission: all 16 `/msg`-touching scripts enumerated above.

## Verification

**Live E20 proof (real daemon, current `bus_post.sh`):**
- Two identical-body posts (minted ids) → **distinct rows** `#10091` + `#10092`, neither
  `legacy` nor `deduped`. (The exact false-dedup that hit lead's posts tonight is gone.)
- Two posts with the **same** `BUS_IDEMPOTENCY_KEY` → **same row** `#10093`, second returns
  `"deduped":true`. Retry-safe replay confirmed.

**Tests (literal):**
```
bash tests/test_forge_drift_check.sh  → PASS=8 FAIL=0   (incl. new envelope-id-minted assertion)
pytest tests/test_bus_post.py -q      → 44 passed, 1 warning in 19.35s
payload build: json.loads OK, keys incl. idempotency_key (non-blank uuid4)
bash -n scripts/forge_drift_check.sh  → clean
```

## Gate plan
Two-gate per dispatch: deputy Claude review + a non-author run → lead merge. Unblocks lead
flipping `BRISEN_LAB_REQUIRE_ENVELOPE_ID` (step 2).
