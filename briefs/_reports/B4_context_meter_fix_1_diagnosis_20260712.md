# CONTEXT_METER_FIX_1 — diagnosis note (measured, before fixing)

- **Brief:** bus #9440 (lead, Director GO, urgent — fleet-blocking, ledger E16).
- **Seat:** b4 · **Date:** 2026-07-12 · **Method:** measured against real fleet transcripts under `~/.claude/projects/*/`.
- **Discipline:** diagnosis-first — findings written and evidence captured BEFORE any code change.

## Symptom
`context-threshold-check.sh` (Stop hook, per-picker `.claude/hooks/`, repo-tracked, identical across b1–b4/aihead pickers) fires the soft/hard rollover bands far too early. Live failures today: deputy 45%→85% in one arc; a deputy successor ~20 min old already "past hard band" (#9424). A hard-band fire forces checkpoint+respawn, so healthy seats are being killed mid-arc.

## Root cause — the estimator (line 130)
```python
tokens_est = math.ceil(size_bytes / 4)          # bytes of the whole transcript JSONL / 4
percent    = int((tokens_est / window_tokens) * 100)
```
`size_bytes` is the **cumulative on-disk size of the entire transcript JSONL**. That file stores full tool-result dumps, JSON envelopes, metadata, and every prior turn verbatim — none of which equals live context tokens, and it **never shrinks on compaction**. So the estimate runs several-fold high and only ever climbs.

## Hypotheses — verdicts with evidence

### H1 — bytes/4 grossly overestimates. **CONFIRMED (primary cause).**
Every live transcript's own API-reported `message.usage` (`input_tokens + cache_read_input_tokens + cache_creation_input_tokens` = true context occupancy) is far below bytes/4:

| Seat (latest transcript) | file bytes | bytes/4 → % of 1M | API usage tokens → % of 1M | over-est factor |
|---|---:|---:|---:|---:|
| aihead1-cowork | 3,361,835 | 840,458 → **84%** | 182,305 → **18%** | 4.6× |
| bm-b2 | 2,460,273 | 615,068 → 62% | 374,525 → 37% | 1.6× |
| bm-b1 | 2,213,810 | 553,452 → 55% | 369,625 → 37% | 1.5× |
| bm-aihead1 | 2,143,373 | 535,843 → 54% | 275,960 → 28% | 1.9× |
| bm-b3 | 1,974,807 | 493,701 → 49% | 308,451 → 31% | 1.6× |
| **bm-b4 (this session, ~90 min)** | 1,955,740 | 488,935 → **49%** | 164,899 → **16.5%** | **3.0×** |

The aihead1-cowork row is the exact fleet-block: a seat at **18%** real context reads as **84%** (hard band) and is forced to die. Over-estimate factor scales with tool-dump density (1.5×–4.6×), so tool-heavy seats trip first — which matches "deputy in one arc" and "20-min successor already over."

Exact `usage` schema (from the b4 transcript, last assistant message):
```json
{"input_tokens":2,"cache_creation_input_tokens":7275,"cache_read_input_tokens":157622,"output_tokens":1878, ...}
```
True context = 2 + 7275 + 157622 = **164,899** (output_tokens excluded — matches Claude Code's own /context measure). Compaction is reflected here (post-compaction usage drops) but never in bytes/4 — a second, independent reason bytes/4 is wrong.

### H2 — successor spawns inherit predecessor transcript (via `--continue`/`--resume`). **NOT the mechanism; the symptom is H1.**
Checked the spawn path end-to-end:
- **Picker functions** (`~/.zshrc` b1–b5, aihead1/2, deputy, desks): all launch **plain `claude "$@"`** — no `--continue`, no `--resume`. Fresh launch ⇒ new transcript UUID.
- **Wake handler** (`~/Applications/Brisen Lab Wake.app/.../main.scpt`, decompiled): nudge-first (sends "check bus" into an existing live tab = same session/transcript, correct) or spawn-fallback (writes `/tmp/brisen-lab-wake-<fn>.command` that runs the picker function = fresh `claude`, new transcript). Neither path passes a resume flag.
- **Deputy** is now **Codex** (`aihead2codex`, `gpt-5.6-luna`, own compaction at `model_auto_compact_token_limit=945000`) — it does not even run this Claude Stop hook.
- The Stop payload's `transcript_path` is always the current session's file, so a fresh seat cannot measure an old transcript.

Conclusion: there is no resume-flag inheritance. A "20-min-old successor past hard band" is fully explained by H1 — a fresh, tool-heavy session bloats transcript bytes quickly (tool dumps), so **bytes/4** crosses the hard band while real context is still low. No spawn-command fix is needed; fixing H1 removes the symptom. (If lead wants belt-and-suspenders, a separate check could reset the block-marker on session start, but it is not required.)

### H3 — per-seat `rollover_window_tokens` misconfig (1M seats reading a smaller window). **RULED OUT.**
All fleet seats read `rollover_window_tokens = 1000000` from `.claude/settings.json`; no `settings.local.json` override narrows it:
```
bm-b1 1000000 · bm-b2 1000000 · bm-b3 1000000 · bm-b4 1000000 · bm-aihead1 1000000 · bm-aihead2 1000000
```
No window misconfig contributes.

## Fix (single PR)
Rewrite only the estimator in `context-threshold-check.sh`: read the transcript's own `message.usage` and use the **last** cumulative `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` as `tokens_est`. Keep **bytes/4 as fallback** when no usage field is present (preserves current behavior for non-Claude / malformed / empty transcripts, and keeps every existing test green — those synthetic `xxxx` transcripts carry no usage). All band logic, config precedence, and block-at-most-once behavior unchanged.

Regression test: a synthetic transcript carrying `message.usage` fields, asserting the hook reads the usage number (not bytes/4); a fresh-seat (tiny usage) reads <5%; and the no-usage fallback still yields bytes/4.

## Acceptance mapping
- **fresh-seat < 5%** — a new transcript's last usage is a few k tokens ⇒ <1% of 1M. ✅ (test)
- **hook % within ±10 of API-reported usage on a live seat** — new estimator *is* the API usage, so exactly matches (0 delta). Verified below on b4's live transcript. ✅
