# B3 — Cortex V1 first real cycle on AO matter — 2026-04-28

**Verdict:** **FAIL — `finance` specialist timeout from local network.** Same capability-specific pattern as russo_*/legal previously identified. STOP criteria triggered per brief: surfacing cycle_id + which Phase 3a pick failed.

## Cycle invocation

- **cycle_id:** `8ba8efc3-2d7d-4371-afc2-08a4107237e7`
- **matter_slug:** `oskolkov`
- **triggered_by:** `director`
- **CORTEX_DRY_RUN:** `false` (live mode)
- **CORTEX_LIVE_PIPELINE:** `true`
- **CORTEX_PIPELINE_ENABLED:** `false` (manual fire, no auto-dispatch)
- **Question:** *"What is AO's actual intention by getting in touch with Siegfried and Constantinos regarding meeting dates with them — without first informing Brisen about our plans to be in Baden-Baden? Counterparty-intent analysis wanted: what is AO trying to achieve, what should Brisen do about it, and what is the recommended response sequence?"*

## Phase progression

| Phase | Order | Artifact | Bytes | At (T+) | Note |
|---|---:|---|---:|---:|---|
| sense | 1 | cycle_init | 82 | +0.0s | OK |
| load | 2 | phase2_context | 18859 | +1.2s | OK (vault + curated) |
| reason | 3 | meta_reason | 3003 | +19.1s | Phase 3a Opus call OK; **3 caps picked** |
| reason | 4 | specialist_invocation | 189 | +3:21 | **finance timeout 60s × 3 = 180s** |
| archive | 6 | cycle_archive | 124 | +4:08 | Phase 6 archived terminal `failed` |

## Phase 3a picks

```json
{
  "caps_planned": ["finance", "sales", "game_theory"],
  "classification": "other",
  "evidence": {
    "finance":     ["(?i)\\b(constantinos|thomas.leitner)\\b"],
    "sales":       ["Baden.Baden|Cap.Ferrat|Kitzbuehel|villa|residence|property.sale"],
    "game_theory": ["cortex-config:games_relevant"]
  }
}
```

Three regex hits on the real question:
- `finance` triggered by mention of "Constantinos" (real-person name regex)
- `sales` triggered by "Baden-Baden" (geo-location regex for property/event sites)
- `game_theory` triggered by cortex-config opt-in (matter has `games_relevant: true`) AND a generic negotiation pattern in the question text

Phase 3a meta-reason produced 3003 bytes (vs ~1100 in smoke cycles) — a richer Opus output for a real question.

## Phase 3b — `finance` blocked the cycle

```json
{
  "capability_slug": "finance",
  "success": false,
  "attempts": 3,
  "error": "timeout after 60s on attempt 3",
  "duration_seconds": 0.0,
  "cost_tokens": 0,
  "cost_dollars": 0.0
}
```

`finance` consumed the full **180s (60s × 3 retries)** from the 300s outer cycle cap, leaving no time for `sales` or `game_theory` to run. After Phase 3b's first specialist exhausted its retry budget, `cortex_phase3_invoker.py:188` did not short-circuit; the outer `asyncio.wait_for(maybe_run_cycle, 300s)` cancelled the loop before specialist 2 could start.

## Phase 3c / Phase 4 / Phase 5

**Never reached.** No `synthesis`, `proposal_card`, or `dry_run_marker` (the latter would not be expected anyway in live mode). No Slack DM, no GOLD write.

## Wall-clock + cost

- **DB-side:** 248.5s (`started_at`→`completed_at` in `cortex_cycles`)
- **Python wall:** 392.1s (process startup + DB pool init dominated outside the cycle)
- **Cost tokens:** 2146
- **Cost dollars:** $0.0617

Cost is only Phase 3a meta-reason; the three `finance` retries spent 180s of wall-clock but produced zero billable tokens (Anthropic call never returned).

## Slack DM

- **Sent:** NO
- **Reason:** Phase 4 propose never reached; cycle terminated in Phase 3b.

## Pattern summary — the capability-timeout shortlist

Confirmed-working specialists from B3 local network (5 smoke cycles + cycle attempt 5):
- ✅ `sales` (14.8s, 1 attempt)

Confirmed-timeout specialists from B3 local network (60s × 3 retries):
- ❌ `russo_cy` (cycle 1 attempt 2)
- ❌ `russo_ai` (cycle 1 attempt 4)
- ❌ `legal` (suspected — bundled with russo_cy disable)
- ❌ **`finance` (this cycle)**

The pattern is: capabilities whose tool-use chain pulls heavily on vault/internal data (compliance lookups, financial-figure aggregation, case-law) time out from outside Render's network. Capabilities with lighter tool-use chains (sales) complete cleanly.

Likely root cause: `capability_runner.run_single` makes outbound HTTP calls that resolve fast inside Render's container (private network egress) but slow from B3's local network because they may go through `baker-master.onrender.com` ingress, which adds latency that compounds across multiple tool-use turns.

## Recommendations to A

1. **Immediate (to clear the cycle):** Disable `finance` too, then refire. `finance` joining russo_*/legal on the disabled list is consistent with the prior pattern and unblocks the immediate cycle. Phase 3a will likely fall back to `sales` + `game_theory` (which are still active — `game_theory` has yet to be tested live; it may also time out — if so, disable it too and surface the next picked cap).

2. **Strategic (V1.1 follow-up):** root-cause the local-network timeout for `finance`/`russo_*`/`legal`. Hypothesis: their tool-use chains call out to Render-internal endpoints (e.g., `baker-master.onrender.com/mcp` or vault-search) that are slow from outside Render. If true, the fix is to either:
   - move cycle invocation inside Render (Render Job, scheduled cron, or admin POST endpoint)
   - or extend `SPECIALIST_TIMEOUT_S` from 60s → 180s for cold-network invocations

3. **Tactical (right now if A wants the cycle to land tonight):** disable `finance` via baker_raw_write (same pattern as the prior 8 caps disabled) and dispatch retry. I'm idle on this until A picks a path.

## Verdict

**FAIL** — Phase 3b `finance` specialist timeout. Cycle archived as `failed` at +4:08 from start. No Slack DM, no GOLD write, no proposal artifact. Pattern matches prior local-network-timeout findings for `russo_*` + `legal`; `finance` is a new addition to the shortlist.

## Notification-style summary for A

```
cycle_id=8ba8efc3-2d7d-4371-afc2-08a4107237e7 verdict=FAIL
phase3a_picked=['finance','sales','game_theory']
phase3b_blocked_on=finance (timeout 60s × 3 = 180s)
cost=$0.0617 wall=248.5s DB / 392s python
slack_dm=NO (Phase 4 never reached)
recommended pivot: disable `finance` then refire — same as prior russo_*/legal pattern
```

---

## Attempts 2 + 3 — finance disabled, identical question, same outcome

After A disabled `finance` (mailbox attempt-2 dispatch), two consecutive refires of the same Director question. Both FAIL with the same trajectory; A's mailbox close-out treats them as a single "attempt 2" since they exercise the same disabled-set scenario. Documented separately here because each is a distinct DB cycle with its own cost.

### Cycle 56f7803f-714f-49d9-9d0f-167082f21bf0 (post-finance-disable refire #1, 21:47Z)

```
status=failed cost=$0.0649 wall=186.3s DB / 374.6s python
phase3a_picked=["sales", "game_theory"]
phase3b_blocked_on=sales (timeout 60s × 3 = 180s)
```

### Cycle 110b4696-7d73-4602-aff1-8ec655729e62 (post-finance-disable refire #2, 21:52Z)

```
status=failed cost=$0.0693 wall=249.6s DB / 374.5s python
phase3a_picked=["sales", "game_theory"]   (deterministic; identical to refire #1)
phase3b_blocked_on=sales (timeout 60s × 3 = 180s)
```

This is the cycle A's mailbox refers to as `attempt_2`.

### Three-cycle accounting (full local-dispatch tally for this brief)

| cycle_id | DB wall | cost | first specialist | A's mailbox label |
|---|---:|---:|---|---|
| `8ba8efc3` | 248.5s | $0.0617 | finance | attempt_1 |
| `56f7803f` | 186.3s | $0.0649 | sales | (collapsed into attempt_2 in mailbox; intermediate retry) |
| `110b4696` | 249.6s | $0.0693 | sales | attempt_2 |
| **Σ** | — | **$0.1959** | — | total local-dispatch burn |

A's mailbox total `$0.131` excludes the intermediate retry (sum of attempts 1 + 3 in my numbering). My total `$0.1959` includes all three. Both are valid framings; A's is the canonical close-out cost.

### Confirmation of question-weight hypothesis

The identical-question, identical-active-caps refire pair (cycles `56f7803f` and `110b4696`) produced identical Phase 3a picks `["sales", "game_theory"]` and identical first-specialist 60s × 3 timeout patterns. The earlier "sales completes cleanly in 14.8s from local" finding (cycle 1 attempt 5, bland prompt) is now firmly contextualized as **bland-prompt-specific**: rich Director questions trigger heavy vault-tool-use chains in any specialist Phase 3a happens to pick.

The disable-list approach is provably exhausted: each new disable just shifts blame to whichever capability Phase 3a picks next.

### Forward path (per A's close-out)

A's mailbox already pivoted to **B2 building `POST /api/cortex/trigger`** per `BRIEF_CORTEX_TRIGGER_ENDPOINT_1.md` (CODE_2_PENDING.md). This matches the Option 1 recommendation in the attempt-1 strategic-options block above: cycles must run inside Render's network where the tool-use chains have sub-60s latency.

After B2's endpoint deploys, A refires the same AO question via `curl` and the cycle executes inside Render's container — no local-vs-prod split-brain, no whack-a-mole on `active=false`.

### Co-Authored-By (attempts 2 + 3 supplemental)

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
